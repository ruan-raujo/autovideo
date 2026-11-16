from concurrent.futures import ThreadPoolExecutor
import json
import time

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, select

from backend.config import Config
from backend.main import create_app
from models.entities import Job
from services.process_lock import ProcessLock
from tests.test_api import create


def test_real_preparation_creates_manifest_without_media(client, app):
    job = create(client, "../E se a Terra parasse de girar?")
    queue = app.state.queue
    assert queue.claim() == job["id"]
    queue.prepare(job["id"])
    result = queue.get(job["id"])
    assert result.status == "awaiting_renderer"
    assert result.preparation_complete is True
    assert result.video_available is False
    assert result.progress == 0
    assert result.attempts == 1
    path = queue.data_dir / "output" / job["story_id"] / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["topic"] == job["topic"]
    assert manifest["specification"]["duration_seconds"] == 80
    assert manifest["specification"]["frames"] == 2400
    assert manifest["scripts"] == {}
    assert manifest["rendering"] == "awaiting_script"
    assert not list(queue.data_dir.rglob("*.mp4"))
    assert not list((queue.data_dir / "temp").iterdir())


def test_pause_and_cancel_win_over_preparation(client, app):
    queue = app.state.queue
    for action, state, topic in (("pause", "paused", "E se os oceanos secassem?"), ("cancel", "cancelled", "E se a Lua fosse destruída?")):
        job = create(client, topic)
        assert queue.claim() == job["id"]
        queue.control(job["id"], action)
        queue.prepare(job["id"])
        assert queue.get(job["id"]).status == state
        assert not (queue.data_dir / "output" / job["story_id"]).exists()


def test_interruption_recovery_preserves_pauses(client, app):
    queue = app.state.queue
    active = create(client, "E se a humanidade desaparecesse?")
    paused = create(client, "E se os dinossauros ainda existissem?")
    queue.control(paused["id"], "pause")
    queue.claim()
    stale = queue.data_dir / "temp" / f"{active['id']}.json.tmp"
    stale.write_text("incompleto")
    unrelated = queue.data_dir / "temp" / "pessoal.json.tmp"
    unrelated.write_text("preservar")
    assert queue.recover() == 1
    assert not stale.exists()
    assert unrelated.read_text() == "preservar"
    assert queue.get(active["id"]).status == "queued"
    assert queue.get(paused["id"]).status == "paused"
    assert "reinício" in queue.get(active["id"]).events[-1].message


def test_atomic_claims_never_duplicate_work(client, app):
    expected = {create(client, f"Tema científico número {number}")["id"] for number in range(8)}
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(lambda _: app.state.queue.claim(), range(12)))
    claimed = [value for value in claims if value]
    assert len(claimed) == len(set(claimed)) == 8
    assert set(claimed) == expected


def test_io_failure_is_persisted_and_can_retry(client, app, monkeypatch):
    from services import queue as queue_module
    queue = app.state.queue
    job = create(client)
    queue.claim()
    original_replace = queue_module.os.replace

    def fail_replace(*args):
        raise PermissionError("injected disk failure")

    monkeypatch.setattr(queue_module.os, "replace", fail_replace)
    queue.prepare(job["id"])
    result = queue.get(job["id"])
    assert result.status == "failed"
    assert result.error
    assert not list((queue.data_dir / "temp").iterdir())
    monkeypatch.setattr(queue_module.os, "replace", original_replace)
    queue.control(job["id"], "resume")
    queue.prepare(queue.claim())
    result = queue.get(job["id"])
    assert result.status == "awaiting_renderer"
    assert result.error is None
    assert result.attempts == 2


def test_data_and_settings_survive_server_restart(tmp_path):
    config = Config(data_dir=tmp_path / "persistent", worker_enabled=False)
    first = create_app(config)
    with TestClient(first) as client:
        job = create(client)
        first.state.queue.claim()
        client.put("/api/settings", json={"worker_poll_seconds": 0.2})
    second = create_app(Config(data_dir=config.data_dir, worker_enabled=True))
    with TestClient(second) as client:
        for _ in range(50):
            result = client.get(f"/api/videos/{job['id']}").json()
            if result["status"] == "awaiting_renderer":
                break
            time.sleep(0.05)
        assert result["status"] == "awaiting_renderer"
        assert result["attempts"] == 2
        assert client.get("/api/settings").json()["queue"]["worker_poll_seconds"] == 0.2
        assert client.get("/api/health").json()["worker"]["running"] is True
        assert any("reinício" in event["message"] for event in result["events"])
    assert not second.state.worker.thread.is_alive()


def test_schema_contains_all_required_tables(client, app):
    assert set(inspect(app.state.engine).get_table_names()) == {
        "stories", "scripts", "scenes", "jobs", "videos", "settings", "visual_assets", "generation_history", "ai_requests", "batches",
    }


def test_second_server_cannot_recover_another_workers_jobs(tmp_path):
    lock1 = ProcessLock(tmp_path / "server.lock")
    lock2 = ProcessLock(tmp_path / "server.lock")
    lock1.acquire()
    try:
        with pytest.raises(RuntimeError, match="já está aberto"):
            lock2.acquire()
    finally:
        lock1.release()
    lock2.acquire()
    lock2.release()
