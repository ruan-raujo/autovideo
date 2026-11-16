from copy import deepcopy

from models.entities import Job, Script
from sqlalchemy import select

from tests.test_stage2 import prepared


def test_save_two_languages_and_shared_visuals(client, app, monkeypatch):
    from services import queue as module
    monkeypatch.setattr(module, "readiness", lambda *args: {"ready": True, "checks": {}})
    job = prepared(client, app)
    scripts = client.get("/api/examples/sun").json()["scripts"]
    for language in ("PT", "EN"):
        response = client.put(f"/api/videos/{job['id']}/script", json=scripts[language])
        assert response.status_code == 200, response.text
    result = client.post(f"/api/videos/{job['id']}/render", json={"languages":["PT","EN"]})
    assert result.status_code == 202
    assert result.json()["script_languages"] == ["PT", "EN"]
    with app.state.queue.sessions() as session:
        assert session.get(Job, job["id"]).render_languages == ["PT", "EN"]
    pt = client.get(f"/api/videos/{job['id']}/script?language=PT").json()["script"]
    en = client.get(f"/api/videos/{job['id']}/script?language=EN").json()["script"]
    assert en["scenes"][0]["title"] != pt["scenes"][0]["title"]
    for left, right in zip(pt["scenes"], en["scenes"], strict=True):
        for key in ("background", "elements", "camera"):
            assert left[key] == right[key]


def test_bilingual_render_refuses_missing_english(client, app, monkeypatch):
    from services import queue as module
    monkeypatch.setattr(module, "readiness", lambda *args: {"ready": True, "checks": {}})
    job = prepared(client, app)
    example = client.get("/api/examples/sun").json()
    client.put(f"/api/videos/{job['id']}/script", json=example["script"])
    assert client.post(f"/api/videos/{job['id']}/render", json={"languages":["PT","EN"]}).status_code == 409
