"""One complete 80-second PT render through the API, with isolated data."""
import hashlib
import json
from pathlib import Path
import shutil
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
    installed = Config()
    example = json.loads((ROOT / "assets/examples/sun-disappears.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="autovideo-stage2-") as directory:
        config = Config(data_dir=Path(directory), worker_enabled=True,
                        ffmpeg_path=executable("ffmpeg", installed), ffprobe_path=executable("ffprobe", installed), voice_path=voice_model(installed))
        app = create_app(config)
        with TestClient(app) as client:
            response = client.post("/api/videos", json={"topic": example["topic"]})
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            for _ in range(100):
                job = client.get(f"/api/videos/{job_id}").json()
                if job["status"] == "awaiting_renderer":
                    break
                time.sleep(.05)
            response = client.put(f"/api/videos/{job_id}/script", json=example["script"])
            assert response.status_code == 200, response.text
            response = client.post(f"/api/videos/{job_id}/render")
            assert response.status_code == 202, response.text
            last_progress = -1
            deadline = time.monotonic()+1800
            while time.monotonic() < deadline:
                job = client.get(f"/api/videos/{job_id}").json()
                if job["progress"] != last_progress:
                    print(f"{job['progress']}% {job['status']}: {job['message']}", flush=True)
                    last_progress = job["progress"]
                if job["status"] == "completed":
                    break
                if job["status"] == "failed":
                    for log in (config.data_dir / "logs").glob("*.log"):
                        print(log.name, log.read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
                    raise AssertionError(job["error"])
                time.sleep(.5)
            assert job["status"] == "completed", job
            video = client.get(f"/api/videos/{job_id}/download/PT")
            assert video.status_code == 200
            preview = client.get(f"/api/videos/{job_id}/preview", headers={"Range": "bytes=0-1023"})
            assert preview.status_code == 206 and len(preview.content) == 1024
            subtitles = client.get(f"/api/videos/{job_id}/subtitles")
            assert subtitles.status_code == 200 and "-->" in subtitles.text
            report = client.get(f"/api/videos/{job_id}/validation").json()
            assert report["validation"]["passed"]
            assert client.get(f"/api/videos/{job_id}/download/EN").status_code == 409
            target = ROOT / "output" / "validacao_etapa2_PT.mp4"
            target.write_bytes(video.content)
            (ROOT / "output" / "validacao_etapa2_PT.srt").write_bytes(subtitles.content)
            report["file_sha256"] = hashlib.sha256(video.content).hexdigest()
            report["api_preview_range"] = "passed"
            report["scope"] = "stage2_PT_only"
            (ROOT / "tests/artifacts/stage2-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            path = app.state.queue.media_path(job_id).parent
            for name in ("narration_fit.json", "word_timings.json", "scene_001_preview.jpg", "scene_004_preview.jpg", "scene_008_preview.jpg"):
                shutil.copyfile(path / name, ROOT / "tests/artifacts" / name)
            print(f"PASS: {target}", flush=True)


if __name__ == "__main__":
    main()
