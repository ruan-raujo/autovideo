from uuid import uuid4

import pytest


def create(client, topic="E se o Sol desaparecesse?"):
    response = client.post("/api/videos", json={"topic": topic})
    assert response.status_code == 202, response.text
    return response.json()


def test_create_list_and_details(client):
    job = create(client)
    assert job["status"] == "queued"
    assert job["video_available"] is False
    assert job["progress"] == 0
    assert len(job["events"]) == 1
    listed = client.get("/api/videos").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == job["id"]
    assert client.get(f"/api/videos/{job['id']}").json()["topic"] == job["topic"]


@pytest.mark.parametrize("topic", ["", "    ", "abc", "123456789", "?!!!!", "a" * 301, "Teste\x00de tema"])
def test_invalid_topics(client, topic):
    assert client.post("/api/videos", json={"topic": topic}).status_code == 422
    assert client.get("/api/videos").json()["total"] == 0


def test_topic_normalization_and_duplicate_history(client):
    job = create(client, "  E se a   inteligência artificial dominasse o mundo? ")
    assert "   " not in job["topic"]
    client.post(f"/api/videos/{job['id']}/cancel")
    duplicate = client.post("/api/videos", json={"topic": "E SE A INTELIGENCIA ARTIFICIAL DOMINASSE O MUNDO!!!"})
    assert duplicate.status_code == 409
    assert client.get("/api/videos").json()["total"] == 1


def test_state_transitions(client):
    job_id = create(client)["id"]
    for action, expected in (("pause", "paused"), ("resume", "queued"), ("cancel", "cancelled")):
        result = client.post(f"/api/videos/{job_id}/{action}")
        assert result.status_code == 200
        assert result.json()["status"] == expected
    assert client.post(f"/api/videos/{job_id}/resume").status_code == 409
    assert client.post(f"/api/videos/{job_id}/cancel").status_code == 409
    assert len(client.get(f"/api/videos/{job_id}").json()["events"]) == 4


def test_filter_pagination_and_counts(client):
    first = create(client, "E se a Lua desaparecesse?")
    second = create(client, "E se a Terra parasse de girar?")
    client.post(f"/api/videos/{first['id']}/pause")
    result = client.get("/api/videos?status=paused&limit=1").json()
    assert result["total"] == 1
    assert result["counts"] == {"paused": 1, "queued": 1}
    assert result["items"][0]["id"] == first["id"]
    assert client.get("/api/videos?limit=1&offset=1").json()["items"][0]["id"] == first["id"]
    assert client.get("/api/videos?limit=101").status_code == 422
    assert client.get("/api/videos?status=invented").status_code == 422


def test_settings_validation_and_persistence(client):
    assert client.get("/api/settings").json()["video_specification"]["frames"] == 2400
    assert client.put("/api/settings", json={"worker_poll_seconds": 0.3, "max_concurrent_jobs": 1}).status_code == 200
    assert client.get("/api/settings").json()["queue"]["worker_poll_seconds"] == 0.3
    assert client.put("/api/settings", json={"max_concurrent_jobs": 2}).status_code == 422
    assert client.put("/api/settings", json={"worker_poll_seconds": 0}).status_code == 422
    assert client.put("/api/settings", json={"arbitrary_path": "C:/"}).status_code == 422


def test_dependencies_and_capabilities_are_honest(client):
    result = client.get("/api/health")
    assert result.status_code == 200
    health = result.json()
    assert health["database"] == "ok"
    assert health["stage"] >= 3
    assert health["capabilities"]["render_video"] is True
    assert isinstance(health["media"]["ready"], bool)
    assert health["worker"]["enabled"] is False
    assert "ffprobe" in health["dependencies"]


def test_unimplemented_features_do_not_simulate_success(client):
    job = create(client)
    assert client.post("/api/videos/batch", json={"count": 10}).status_code == 202
    assert client.post("/api/topics/generate").status_code == 202
    assert client.get(f"/api/videos/{job['id']}/download/PT").status_code == 409
    assert client.get(f"/api/videos/{job['id']}/download/FR").status_code == 422


def test_missing_and_malformed_ids(client):
    assert client.get(f"/api/videos/{uuid4()}").status_code == 404
    assert client.post(f"/api/videos/{uuid4()}/pause").status_code == 404
    assert client.get("/api/videos/not-a-uuid").status_code == 422


def test_local_origin_and_body_limits(client):
    assert client.post("/api/videos", json={"topic": "Um tema externo"}, headers={"origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/videos", json={"topic": "Um tema externo"}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/videos", content="topic=teste", headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 415
    assert client.post("/api/videos", content='x' * 17000, headers={"content-type": "application/json"}).status_code == 413
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert client.post("/api/videos", json={"topic": "Um tema permitido"}, headers={"origin": "http://testserver"}).status_code == 202


def test_frontend_openapi_and_file_protection(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Novo projeto" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    for path in ("/static/styles.css", "/static/app.js", "/static/favicon.svg", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 200
    assert client.get("/output/project.json").status_code == 404
    assert client.get("/static/%2e%2e/backend/config.py").status_code == 404
    assert "/api/videos/{job_id}/pause" in client.get("/openapi.json").json()["paths"]
