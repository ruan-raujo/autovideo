"""Measure the installed local model, then release it before media processing."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import Config
from services.ollama_client import OllamaClient


def main():
    client=OllamaClient(Config())
    try:
        result=client.request("/api/generate",{"model":client.model,"stream":False,"think":False,"keep_alive":30,
            "format":"json","prompt":"Responda JSON com title e narration. Em português brasileiro, explique em uma frase que a luz solar demora cerca de oito minutos para chegar à Terra.",
            "options":{"num_ctx":4096,"num_predict":200,"num_thread":2,"temperature":.7,"top_p":.8,"top_k":20}},timeout=300)
        report={"model":client.model,"loaded":client.request("/api/ps"),"result":json.loads(result["response"]),
                "tokens_per_second":round(result.get("eval_count",0)/max(.0001,result.get("eval_duration",1)/1e9),2)}
        destination=ROOT/"tests/artifacts/ai-hardware.json"
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=True,indent=2))
    finally:
        client.unload()


if __name__=="__main__":
    main()
