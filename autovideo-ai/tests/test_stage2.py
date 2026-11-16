from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
import pytest
from sqlalchemy import func, select

from animation.renderer import SceneRenderer
from backend.config import Config, ROOT
from backend.main import create_app
from models.entities import Job, Scene, Script
from models.schemas import ScriptInput, QueueSettings
from services.media_tools import Interrupted, MediaError
from services.narration import synthesize_scene
from services.render_supervisor import render_project
from services.subtitles import write_subtitles
from tests.test_api import create


def example_script():
    return json.loads((ROOT / "assets/examples/sun-disappears.json").read_text(encoding="utf-8"))["script"]


def prepared(client, app):
    job = create(client)
    app.state.queue.prepare(app.state.queue.claim())
    return job


def test_structured_script_validation_and_atomic_edits(client, app):
    job = prepared(client, app)
    script = example_script()
    route = f"/api/videos/{job['id']}/script"
    assert client.put(route, json=script).status_code == 200
    assert client.get(route).json()["script"]["language"] == "PT"
    assert client.get(f"/api/videos/{job['id']}").json()["script_available"] is True
    broken = deepcopy(script)
    broken["scenes"][0]["frames"] += 1
    assert client.put(route, json=broken).status_code == 422
    assert client.get(route).json()["script"]["scenes"][0]["frames"] == 150
    script["scenes"][0]["title"] = "Um título revisado"
    assert client.put(route, json=script).status_code == 200
    with app.state.queue.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Script)) == 1
        assert session.scalar(select(func.count()).select_from(Scene)) == 10


@pytest.mark.parametrize("change", ["language", "frames", "words", "injection", "external_asset"])
def test_script_rejects_incompatible_or_unsafe_data(client, app, change):
    job = prepared(client, app)
    script = example_script()
    if change == "language": script["language"] = "FR"
    if change == "frames": script["scenes"][0]["frames"] = 151
    if change == "words":
        for scene in script["scenes"]: scene["narration"] = "Texto curto."
    if change == "injection": script["scenes"][0]["narration"] = "Texto {\\an8} de legenda insegura."
    if change == "external_asset": script["scenes"][0]["elements"][0]["asset"] = "../../arquivo"
    assert client.put(f"/api/videos/{job['id']}/script", json=script).status_code == 422
    assert client.get(f"/api/videos/{job['id']}/script").json()["script"] is None


def test_render_requires_dependencies_and_script(client, app, monkeypatch):
    from services import queue as module
    job = prepared(client, app)
    route = f"/api/videos/{job['id']}/render"
    monkeypatch.setattr(module, "readiness", lambda _: {"ready": False, "checks": {"voice_pt": False}})
    assert client.post(route).status_code == 503
    monkeypatch.setattr(module, "readiness", lambda _: {"ready": True, "checks": {}})
    assert client.post(route).status_code == 409
    assert client.put(f"/api/videos/{job['id']}/script", json=example_script()).status_code == 200
    assert client.post(route).status_code == 202
    assert client.post(route).status_code == 409


def test_render_pause_resume_cancel_use_real_states(client, app, monkeypatch):
    from services import queue as module
    monkeypatch.setattr(module, "readiness", lambda _: {"ready": True, "checks": {}})
    job = prepared(client, app)
    queue = app.state.queue
    queue.save_script(job["id"], ScriptInput.model_validate(example_script()))
    queue.request_render(job["id"])
    assert queue.claim() == job["id"]
    assert queue.get(job["id"]).status == "synthesizing"
    queue.control(job["id"], "pause")
    resumed = queue.control(job["id"], "resume")
    assert resumed.status == "render_queued"
    assert resumed.events[-1].status == "render_queued"
    assert resumed.video_available is False
    queue.control(job["id"], "cancel")
    assert queue.claim() is None
    assert client.get(f"/api/videos/{job['id']}/preview").status_code == 409


def test_active_script_cannot_be_changed(client, app, monkeypatch):
    from services import queue as module
    monkeypatch.setattr(module, "readiness", lambda _: {"ready": True, "checks": {}})
    job = prepared(client, app)
    route = f"/api/videos/{job['id']}/script"
    client.put(route, json=example_script())
    client.post(f"/api/videos/{job['id']}/render")
    assert client.put(route, json=example_script()).status_code == 409


def test_frames_move_svg_objects_not_only_camera():
    scene = ScriptInput.model_validate(example_script()).scenes[0]
    scene.camera.zoom_start = scene.camera.zoom_end = 1
    scene.camera.pan_x = scene.camera.pan_y = 0
    renderer = SceneRenderer(scene, 0, 10)
    first = np.asarray(renderer.frame(30))
    later = np.asarray(renderer.frame(90))
    assert first.shape == (1920, 1080, 3)
    assert np.count_nonzero(np.any(first[600:1300] != later[600:1300], axis=2)) > 1000


def test_subtitles_preserve_every_word_and_highlight_timing(tmp_path):
    words = [{"word": word, "start": index*.5, "end": index*.5+.4} for index, word in enumerate("Uma história com palavras completas e conclusão.".split())]
    write_subtitles(words, tmp_path, 62)
    srt = (tmp_path / "subtitles.srt").read_text(encoding="utf-8")
    ass = (tmp_path / "subtitles.ass").read_text(encoding="utf-8-sig")
    assert all(word["word"] in srt for word in words)
    assert "\\k" in ass and "1080" in ass and "1920" in ass
    assert "conclusão." in ass


def test_too_long_narration_is_rejected_without_cutting():
    from types import SimpleNamespace
    samples = np.zeros(12*22050, dtype=np.int16)
    chunk = SimpleNamespace(audio_int16_array=samples, phoneme_alignments=[
        SimpleNamespace(phoneme="a", num_samples=6*22050),
        SimpleNamespace(phoneme=" ", num_samples=0),
        SimpleNamespace(phoneme="b", num_samples=6*22050),
    ])
    voice = SimpleNamespace(config=SimpleNamespace(sample_rate=22050), synthesize=lambda *args, **kwargs: [chunk])
    with pytest.raises(MediaError, match="Encurte a fala"):
        synthesize_scene(voice, "Texto extenso", 5, 1)
    assert len(samples) == 12*22050


def test_supervisor_stops_its_process_and_cleans_temporary_files(tmp_path, monkeypatch):
    from services import render_supervisor as module
    config = Config(data_dir=tmp_path)
    config.prepare_directories()
    original = subprocess.Popen
    processes = []

    def slow_child(*args, **kwargs):
        process = original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        processes.append(process)
        return process

    checks = 0
    def checkpoint():
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise Interrupted("Pausa solicitada")

    monkeypatch.setattr(module.subprocess, "Popen", slow_child)
    with pytest.raises(Interrupted):
        render_project(config, str(uuid4()), str(uuid4()), example_script(), QueueSettings(), checkpoint, lambda _: None)
    assert processes[0].poll() is not None
    assert not list((tmp_path / "temp").glob("render_*"))


def test_stage1_database_migration_keeps_history_and_backup(tmp_path):
    config = Config(data_dir=tmp_path / "legacy", worker_enabled=False)
    config.prepare_directories()
    job_id, story_id = str(uuid4()), str(uuid4())
    with sqlite3.connect(config.database_path) as connection:
        connection.executescript("""
        CREATE TABLE stories (id VARCHAR(36) PRIMARY KEY, topic VARCHAR NOT NULL, topic_key VARCHAR NOT NULL UNIQUE, created_at VARCHAR NOT NULL);
        CREATE TABLE jobs (id VARCHAR(36) PRIMARY KEY, story_id VARCHAR NOT NULL UNIQUE REFERENCES stories(id), status VARCHAR NOT NULL CHECK(status IN ('queued','preparing','awaiting_renderer','paused','cancelled','failed')), progress INTEGER NOT NULL, message VARCHAR NOT NULL, error VARCHAR, attempts INTEGER NOT NULL, manifest_path VARCHAR, created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL);
        CREATE TABLE generation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id VARCHAR NOT NULL REFERENCES jobs(id), status VARCHAR NOT NULL, message VARCHAR NOT NULL, created_at VARCHAR NOT NULL);
        """)
        connection.execute("INSERT INTO stories VALUES(?,?,?,?)", (story_id, "Tema antigo preservado", "temaantigo", "2026-11-16"))
        connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)", (job_id, story_id, "paused", 0, "Pausado", None, 3, None, "2026-11-16", "2026-11-16"))
        connection.execute("INSERT INTO generation_history(job_id,status,message,created_at) VALUES(?,?,?,?)", (job_id, "paused", "Evento antigo preservado", "2026-11-16"))
    with TestClient(create_app(config)) as client:
        job = client.get(f"/api/videos/{job_id}").json()
        assert job["status"] == "paused" and job["attempts"] == 3
        assert job["events"][0]["message"] == "Evento antigo preservado"
        assert job["task"] == "prepare"
    backups = list(config.database_path.parent.glob("before-stage2-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as old:
        assert "completed" not in old.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()[0]
    with sqlite3.connect(config.database_path) as migrated:
        assert "completed" in migrated.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()[0]
        assert not migrated.execute("PRAGMA foreign_key_check").fetchall()


def test_media_watchdog_exits_if_its_api_owner_has_disappeared():
    result = subprocess.run([
        sys.executable, "-c",
        "from services.render_job import stop_when_owner_exits; stop_when_owner_exits({'owner_pid':999999999,'owner_created':0})",
    ], cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == 2, result.stderr.decode(errors="replace")
