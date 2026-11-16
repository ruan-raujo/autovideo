from sqlalchemy import func, select
from models.entities import Batch, Story, Job
from tests.test_api import create


def test_batch_membership_group_controls_and_queue_recovery(client, app):
    result = client.post("/api/videos/batch",json={"count":3,"automatic":True})
    assert result.status_code == 202, result.text
    batch = result.json()
    assert len(batch["items"]) == 3
    assert len({item["id"] for item in batch["items"]}) == 3
    assert all(item["batch_id"] == batch["id"] for item in batch["items"])
    assert client.post(f"/api/batches/{batch['id']}/pause").json()["counts"] == {"paused":3}
    app.state.queue.recover()
    assert app.state.queue.claim() is None
    assert client.post(f"/api/batches/{batch['id']}/resume").json()["counts"] == {"queued":3}
    assert client.post(f"/api/batches/{batch['id']}/cancel").json()["counts"] == {"cancelled":3}
    assert len(client.get("/api/batches").json()["items"]) == 1


def test_batch_duplicate_failure_is_atomic(client, app):
    create(client,"E se o Sol desaparecesse?")
    response = client.post("/api/videos/batch",json={"count":2,"automatic":False,"topics":["E se a Lua desaparecesse?","E se o Sol desaparecesse?"]})
    assert response.status_code == 409
    assert client.get("/api/videos").json()["total"] == 1
    assert client.get("/api/batches").json()["items"] == []


def test_batch_bounds_and_manual_topics(client):
    assert client.post("/api/videos/batch",json={"count":21}).status_code == 422
    assert client.post("/api/videos/batch",json={"count":2,"automatic":False}).status_code == 422
    assert client.post("/api/videos/batch",json={"count":2,"topics":["Tema único"]}).status_code == 422
    response = client.post("/api/videos/batch",json={"count":2,"automatic":False,"topics":["E se a Lua desaparecesse?","E se a Terra congelasse?"]})
    assert response.status_code == 202
    assert response.json()["automatic"] is False
