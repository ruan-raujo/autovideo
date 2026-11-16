"""Supervised local AI worker. Models are unloaded before voice measurement."""
import json
from pathlib import Path
import sys
import threading
import traceback

from backend.config import Config
from services.media_tools import MediaError
from services.ollama_client import OllamaClient
from services.story_ai import build_script, generate_topics, repair_and_measure
from services.editorial import review_script
from services.render_job import progress, stop_when_owner_exits


def generate(request, workspace):
    config = Config(data_dir=Path(request["data_dir"]), ollama_url=request["ollama_url"], ollama_model=request["ollama_model"])
    client = OllamaClient(config)
    try:
        progress(workspace, "preparing", 2, "Conectando ao modelo local.")
        if request["mode"] == "topics":
            topics = generate_topics(client, request["count"], request["history"], seed_topic=request.get("seed_topic",""))
            result = {"topics":topics,"model":client.model}
        else:
            topic = request["topic"]
            if request.get("auto_topic"):
                topic = generate_topics(client, 1, request["history"], seed_topic=request.get("seed_topic",""))[0]
            print("Selected topic:",topic,flush=True)
            progress(workspace, "preparing", 10, f"Escrevendo roteiro: {topic}")
            pt = build_script(client, topic, "PT")
            progress(workspace,"preparing",30,"Conferindo coerência e referências do roteiro PT.")
            pt,review_pt=review_script(client,topic,pt)
            progress(workspace,"preparing",45,"Medindo e ajustando a narração PT, sem cortes.")
            pt,fit_pt=repair_and_measure(client,pt,Path(request["voices"]["PT"]),request["settings"]["cpu_threads"])
            progress(workspace, "preparing", 60, "Adaptando o roteiro revisado para inglês.")
            en=build_script(client,topic,"EN",source=pt)
            progress(workspace,"preparing",75,"Conferindo a adaptação inglesa e suas referências.")
            en,review_en=review_script(client,topic,en,source=pt)
            progress(workspace,"preparing",85,"Medindo e ajustando a narração EN, sem cortes.")
            en,fit_en=repair_and_measure(client,en,Path(request["voices"]["EN"]),request["settings"]["cpu_threads"])
            scripts={"PT":pt,"EN":en}; fitting={"PT":fit_pt,"EN":fit_en}
            result = {"topic":topic,"scripts":scripts,"model":client.model,"fitting":fitting,"editorial":{"PT":review_pt,"EN":review_en},"source":"local_ollama","needs_editorial_review":True}
        (workspace / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        progress(workspace, "preparing", 99, "Geração local validada; salvando no banco.")
    finally:
        client.unload()


if __name__ == "__main__":
    workspace = Path(sys.argv[1]).resolve()
    request = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
    threading.Thread(target=stop_when_owner_exits, args=(request,), daemon=True).start()
    try:
        generate(request, workspace)
    except Exception as error:
        traceback.print_exc()
        (workspace / "failure.json").write_text(json.dumps({"message":str(error)[:600] if isinstance(error,MediaError) else "Falha ao gerar o roteiro local. Consulte o log."},ensure_ascii=False),encoding="utf-8")
        sys.exit(1)
