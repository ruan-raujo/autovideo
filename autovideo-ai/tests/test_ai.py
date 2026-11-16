import pytest

from backend.config import Config
from models.entities import AIRequest, Job
from services.media_tools import MediaError
from services.ollama_client import OllamaClient
from services.story_ai import generate_topics
from services.narration import align_linked_words
from tests.test_stage2 import prepared


@pytest.mark.parametrize("url", ["https://127.0.0.1:11434", "http://api.example.com", "http://192.168.1.20:11434"])
def test_ollama_client_rejects_non_local_endpoints(url):
    with pytest.raises(MediaError): OllamaClient(Config(ollama_url=url))


def test_cloud_models_are_refused():
    with pytest.raises(MediaError): OllamaClient(Config(ollama_model="model:cloud"))


def test_linked_english_words_use_real_phoneme_boundaries():
    class Voice:
        def phonemize(self, word):
            return {"on":[["o","n"]], "the":[["d","a"]]}[word]
    assert align_linked_words(Voice(), ["on","the"], [("o",0,10),("n",10,20),("d",20,30),("a",30,40)]) == [(0,20),(20,40)]


def test_ideas_retry_duplicates_without_reusing_history():
    class Client:
        calls = 0
        def generate(self, *args, **kwargs):
            self.calls += 1
            if "evaluations" in args[1].get("properties",{}):
                return {"evaluations":[{"index":index,"valid":True,"reason":"Valid hypothetical change"} for index in range(3)]}
            return {"topics":["E se o SOL desaparecesse?", "E se a Lua fosse azul?", "E se árvores produzissem luz?"]}
    client = Client()
    assert generate_topics(client, 2, ["E se o Sol desaparecesse!"]) == ["E se a Lua fosse azul?", "E se árvores produzissem luz?"]


def test_topic_tasks_are_persistent_and_recovered(client, app):
    response = client.post("/api/topics/generate",json={"count":3})
    assert response.status_code == 202
    task_id = response.json()["id"]
    assert app.state.queue.claim_topics() == task_id
    assert client.get(f"/api/topics/tasks/{task_id}").json()["status"] == "running"
    app.state.queue.recover()
    assert client.get(f"/api/topics/tasks/{task_id}").json()["status"] == "queued"
    assert client.post("/api/topics/generate",json={"count":21}).status_code == 422
    assert client.post(f"/api/topics/tasks/{task_id}/cancel").json()["status"] == "cancelled"
    assert app.state.queue.claim_topics() is None


def test_generation_jobs_are_pausable_and_preserve_options(client, app):
    job = prepared(client, app)
    response = client.post(f"/api/videos/{job['id']}/generate-script",json={"auto_render":True})
    assert response.status_code == 202
    assert app.state.queue.claim() == job["id"]
    with app.state.queue.sessions() as session:
        row = session.get(Job, job["id"])
        old_token = row.render_token
        assert row.task == "generate" and row.generation_options["auto_render"]
    assert client.post(f"/api/videos/{job['id']}/pause").json()["status"] == "paused"
    assert client.post(f"/api/videos/{job['id']}/resume").json()["status"] == "queued"
    with app.state.queue.sessions() as session:
        assert session.get(Job, job["id"]).render_token != old_token
