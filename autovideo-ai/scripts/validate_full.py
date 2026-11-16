"""Real bilingual acceptance test; --automatic exercises the production batch."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from backend.config import Config
from backend.main import create_app
from services.media_tools import executable, voice_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--automatic", action="store_true")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    installed = Config()
    outputs = ROOT / "output" / "acceptance"
    outputs.mkdir(parents=True, exist_ok=True)
    report = {"automatic": args.automatic, "videos": [], "jobs": []}
    state_path = ROOT / "tests/artifacts/full-validation-state.json"
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if args.resume else {}
    directory = state.get("data_dir") or tempfile.mkdtemp(prefix="autovideo-acceptance-",dir=installed.data_dir)
    state["data_dir"] = directory
    state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
    with nullcontext(directory) as directory:
        config = Config(data_dir=Path(directory), worker_enabled=True,
                        ffmpeg_path=executable("ffmpeg", installed), ffprobe_path=executable("ffprobe", installed),
                        voice_path=voice_model(installed), voice_en_path=voice_model(installed, "EN"),
                        ollama_url=installed.ollama_url, ollama_model=installed.ollama_model)
        app = create_app(config)
        with TestClient(app) as client:
            settings = client.get("/api/settings").json()["queue"]
            settings.update({"music_enabled":True,"sfx_enabled":True,"encoder":"auto"})
            assert client.put("/api/settings",json=settings).status_code==200
            example = client.get("/api/examples/sun").json()
            if args.resume:
                jobs=state["jobs"]
                for job_id in jobs:
                    job=client.get(f"/api/videos/{job_id}").json()
                    if job["status"] in ("failed","paused"):
                        response=client.post(f"/api/videos/{job_id}/resume")
                        assert response.status_code==200,response.text
            elif args.automatic:
                response = client.post("/api/videos/batch", json={"count": args.count, "automatic": True})
                assert response.status_code == 202, response.text
                jobs = [item["id"] for item in response.json()["items"]]
            else:
                response = client.post("/api/videos", json={"topic": example["topic"]})
                assert response.status_code == 202, response.text
                job_id = response.json()["id"]
                for _ in range(100):
                    if client.get(f"/api/videos/{job_id}").json()["preparation_complete"]:
                        break
                    time.sleep(.05)
                for language in ("PT", "EN"):
                    response = client.put(f"/api/videos/{job_id}/script", json=example["scripts"][language])
                    assert response.status_code == 200, response.text
                response = client.post(f"/api/videos/{job_id}/render", json={"languages":["EN","PT"]})
                assert response.status_code == 202, response.text
                jobs = [job_id]
            state.update({"jobs":jobs,"automatic":args.automatic or state.get("automatic",False)})
            state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
            report["automatic"]=state["automatic"]
            report["data_dir"]=directory
            deadline = time.monotonic() + 3600*max(1, len(jobs))
            previous = {}
            failed_jobs={}
            while time.monotonic() < deadline:
                complete = True
                for job_id in jobs:
                    job = client.get(f"/api/videos/{job_id}").json()
                    state = (job["status"], job["progress"]//5)
                    if state != previous.get(job_id):
                        print(job_id[:8], job["status"], f"{job['progress']}%", job["message"], flush=True)
                        previous[job_id] = state
                    if job["status"] == "failed":
                        if job_id not in failed_jobs:
                            failed_jobs[job_id]=job["error"]
                            for log in (config.data_dir / "logs").glob(f"{job_id}*.log"):
                                print(log.name,log.read_text(encoding="utf-8",errors="replace")[-3000:],flush=True)
                    complete = complete and job["status"] in ("completed","failed")
                if complete:
                    break
                time.sleep(1)
            assert complete, "Acceptance rendering timed out"
            for number, job_id in enumerate(jobs, 1):
                job = client.get(f"/api/videos/{job_id}").json()
                if job["status"]=="failed":
                    report["jobs"].append(job)
                    continue
                assert job["video_languages"] == ["PT", "EN"], job
                report["jobs"].append(job)
                for language in ("PT", "EN"):
                    video = client.get(f"/api/videos/{job_id}/download/{language}")
                    assert video.status_code == 200
                    metadata = client.get(f"/api/videos/{job_id}/validation?language={language}").json()
                    assert metadata["validation"]["passed"] and metadata["validation"]["language"] == language
                    preview = client.get(f"/api/videos/{job_id}/preview?language={language}", headers={"Range":"bytes=0-1023"})
                    assert preview.status_code == 206
                    name = f"video_{number:03}_{language}"
                    (outputs / f"{name}.mp4").write_bytes(video.content)
                    subtitles = client.get(f"/api/videos/{job_id}/subtitles?language={language}")
                    assert subtitles.status_code == 200 and b"-->" in subtitles.content
                    (outputs / f"{name}.srt").write_bytes(subtitles.content)
                    (outputs / f"{name}.validation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                    script=client.get(f"/api/videos/{job_id}/script?language={language}").json()["script"]
                    (outputs / f"{name}.script.json").write_text(json.dumps(script,ensure_ascii=False,indent=2),encoding="utf-8")
                    source=app.state.queue.media_path(job_id,language=language).parent
                    for artifact in ("word_timings.json","narration_fit.json"):
                        (outputs/f"{name}.{artifact}").write_bytes((source/artifact).read_bytes())
                    report["videos"].append({"language": language, "path": str(outputs / f"{name}.mp4"),
                                             "sha256": hashlib.sha256(video.content).hexdigest(), "metadata": metadata})
            report["failed_jobs"]=failed_jobs
            report["passed"]=not bool(failed_jobs)
            print(f"{len(report['videos'])} real videos validated; {len(failed_jobs)} failed jobs", flush=True)
    (ROOT / "tests/artifacts/full-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert report["passed"],report["failed_jobs"]


if __name__ == "__main__":
    main()
