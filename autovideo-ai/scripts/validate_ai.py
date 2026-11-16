"""Validate real Ollama topics + two timed scripts, without encoding yet."""
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from backend.config import Config
from backend.main import create_app
from services.media_tools import executable, voice_model


def main():
    installed = Config()
    with tempfile.TemporaryDirectory(prefix="autovideo-ai-check-") as directory:
        config = Config(data_dir=Path(directory), worker_enabled=True, ffmpeg_path=executable("ffmpeg",installed),
                        ffprobe_path=executable("ffprobe",installed), voice_path=voice_model(installed), voice_en_path=voice_model(installed,"EN"))
        app = create_app(config)
        with TestClient(app) as client:
            idea = client.post("/api/topics/generate",json={"count":2}).json()
            deadline = time.monotonic()+1200
            while time.monotonic() < deadline:
                idea = client.get(f"/api/topics/tasks/{idea['id']}").json()
                if idea["status"] in {"completed","failed"}: break
                time.sleep(1)
            assert idea["status"] == "completed", idea
            print("Ideas:",json.dumps(idea["result"],ensure_ascii=False),flush=True)
            job = client.post("/api/videos",json={"topic":"E se o Sol desaparecesse?"}).json()
            for _ in range(100):
                job = client.get(f"/api/videos/{job['id']}").json()
                if job["preparation_complete"]: break
                time.sleep(.1)
            response = client.post(f"/api/videos/{job['id']}/generate-script",json={"auto_render":False})
            assert response.status_code == 202, response.text
            previous = None
            while time.monotonic() < deadline:
                job = client.get(f"/api/videos/{job['id']}").json()
                if job["message"] != previous:
                    print(job["status"],job["progress"],job["message"],flush=True)
                    previous = job["message"]
                if job["status"] in {"awaiting_renderer","failed"}: break
                time.sleep(1)
            if job["status"] == "failed":
                for log in (config.data_dir/"logs").glob("*.log"): print(log.read_text(encoding="utf-8",errors="replace")[-6000:])
            assert job["status"] == "awaiting_renderer" and job["script_languages"] == ["PT","EN"], job
            generation = json.loads((config.data_dir/"output"/job["story_id"]/"generation.json").read_text(encoding="utf-8"))
            (ROOT/"tests/artifacts/ai-generation-validation.json").write_text(json.dumps({"ideas":idea,"generation":generation},ensure_ascii=False,indent=2),encoding="utf-8")
            print("PASS real Ollama ideas + timed bilingual scripts",flush=True)


if __name__ == "__main__": main()
