"""Diagnóstico gratuito e independente do servidor: python scripts/check_environment.py."""
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Config
from services.media_tools import executable, readiness, voice_model


def collect():
    config = Config()
    memory = psutil.virtual_memory()
    report = {
        "os": platform.platform(), "python": sys.version.split()[0],
        "cpu_logical": psutil.cpu_count(), "cpu_physical": psutil.cpu_count(logical=False),
        "ram_total_gb": round(memory.total / 1024**3, 2),
        "ram_available_gb": round(memory.available / 1024**3, 2),
        "dependencies": {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "ollama", "piper")},
        "gpu": [],
    }
    report["dependencies"]["ffmpeg"] = str(executable("ffmpeg", config)) if executable("ffmpeg", config) else None
    report["dependencies"]["ffprobe"] = str(executable("ffprobe", config)) if executable("ffprobe", config) else None
    report["dependencies"]["piper"] = "Python package piper-tts" if readiness(config)["checks"]["piper"] else None
    report["voice_pt"] = str(voice_model(config)) if voice_model(config) else None
    report["voice_en"] = str(voice_model(config,"EN")) if voice_model(config,"EN") else None
    report["media_ready"] = readiness(config,("PT","EN"))["ready"]
    from services.ollama_client import OllamaClient
    report["dependencies"]["ollama"] = str(executable("ollama",config)) if executable("ollama",config) else None
    report["ai"] = OllamaClient(config).status()
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            report["gpu"] = result.stdout.strip().splitlines()
        except (OSError, subprocess.TimeoutExpired) as error:
            report["gpu_error"] = str(error)
    return report


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
