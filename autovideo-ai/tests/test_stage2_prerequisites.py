from tests.test_api import create


def test_cannot_edit_script_of_unprepared_paused_project(client):
    job = create(client)
    client.post(f"/api/videos/{job['id']}/pause")
    from tests.test_stage2 import example_script
    response = client.put(f"/api/videos/{job['id']}/script", json=example_script())
    assert response.status_code == 409
    assert "preparado" in response.json()["detail"]
