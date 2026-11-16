"""Local-only Ollama transport with bounded context and explicit model unloading."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from services.media_tools import MediaError, executable, process_flags

SERVER_LOCK = threading.Lock()


class OllamaClient:
    def __init__(self, config):
        self.config = config
        parsed = urllib.parse.urlparse(config.ollama_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise MediaError("Ollama deve usar HTTP no computador local; serviços de nuvem não são usados.")
        if config.ollama_model.endswith(":cloud"):
            raise MediaError("Use um modelo Ollama local, sem o sufixo :cloud.")
        self.url = config.ollama_url.rstrip("/")
        self.model = config.ollama_model

    def request(self, route, payload=None, timeout=10):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.url+route, data=data, headers={"Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            raise MediaError(f"Ollama local indisponível: {error}. Execute instalar_ia.bat.") from error

    def status(self):
        try:
            version = self.request("/api/version", timeout=2)
            models = self.request("/api/tags", timeout=2).get("models", [])
            return {"available":True, "version":version.get("version"), "model":self.model,
                    "model_available":any(item["name"] == self.model or item["name"] == self.model+":latest" for item in models)}
        except MediaError:
            return {"available":False, "model":self.model, "model_available":False}

    def ensure_server(self):
        if self.status()["available"]:
            return
        with SERVER_LOCK:
            if self.status()["available"]:
                return
            binary = executable("ollama", self.config)
            if binary is None:
                raise MediaError("Ollama não está instalado. Execute instalar_ia.bat.")
            self.config.prepare_directories()
            environment = os.environ.copy()
            environment.update({"OLLAMA_HOST":urllib.parse.urlparse(self.url).netloc, "OLLAMA_MODELS":str(self.config.data_dir/"ai_models"),
                                "OLLAMA_NUM_PARALLEL":"1", "OLLAMA_MAX_LOADED_MODELS":"1", "OLLAMA_CONTEXT_LENGTH":"4096",
                                "OLLAMA_KEEP_ALIVE":"0", "OLLAMA_NO_CLOUD":"1", "OLLAMA_FLASH_ATTENTION":"1"})
            with (self.config.data_dir/"logs"/"ollama-server.log").open("ab") as log:
                subprocess.Popen([str(binary), "serve"], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 env=environment, cwd=binary.parent, **process_flags())
            for _ in range(100):
                if self.status()["available"]:
                    return
                time.sleep(.2)
            raise MediaError("Ollama não iniciou no prazo. Consulte logs/ollama-server.log.")

    def pull(self):
        self.ensure_server()
        request = urllib.request.Request(self.url+"/api/pull", data=json.dumps({"model":self.model,"stream":True}).encode(), headers={"Content-Type":"application/json"})
        previous = None
        with urllib.request.urlopen(request, timeout=600) as response:
            for line in response:
                event = json.loads(line)
                if "error" in event:
                    raise MediaError(event["error"])
                status = event.get("status", "")
                if "total" in event and event["total"]:
                    status += f" {event.get('completed',0)*100//event['total']}%"
                if status != previous:
                    print(status, flush=True)
                    previous = status

    def unload(self):
        try:
            self.request("/api/generate", {"model":self.model,"keep_alive":0}, timeout=30)
        except MediaError:
            pass

    def generate(self, prompt, schema, checkpoint=lambda:None, temperature=.3, _plain=False):
        self.ensure_server()
        if not self.status()["model_available"]:
            raise MediaError(f"Modelo {self.model} não instalado. Execute instalar_ia.bat para baixá-lo.")
        if _plain:
            prompt += "\nReturn one complete compact JSON object matching this schema. No explanation. Schema: "+json.dumps(schema)
        payload = {"model":self.model, "prompt":prompt, "format":"json" if _plain else schema, "stream":True, "keep_alive":0,
                   "options":{"num_ctx":4096,"num_predict":2400,"temperature":max(.6,temperature),"top_p":.8,"top_k":20,"min_p":0,"num_thread":2,"repeat_penalty":1.08,"repeat_last_n":256}}
        if self.model.startswith("qwen3"):
            payload["think"] = False
        request = urllib.request.Request(self.url+"/api/generate", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type":"application/json"})
        content = []
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                for line in response:
                    checkpoint()
                    event = json.loads(line)
                    if "error" in event:
                        raise MediaError(event["error"])
                    content.append(event.get("response", ""))
                    if sum(map(len, content)) > 100_000:
                        raise MediaError("Resposta do modelo excedeu o limite configurado.")
            body = "".join(content)
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                print("Invalid model JSON:",len(body),repr(body[:140]),repr(body[-140:]),flush=True)
                raise
        except (OSError, json.JSONDecodeError, MediaError) as error:
            if not _plain:
                return self.generate(prompt, schema, checkpoint, temperature, _plain=True)
            raise MediaError("Ollama não retornou JSON completo: "+str(error)[:180]) from error
        finally:
            self.unload()
