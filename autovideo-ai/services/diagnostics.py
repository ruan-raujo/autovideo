import platform
import shutil
import sqlite3

import psutil
from sqlalchemy import text
from services.media_tools import executable, readiness, voice_model


def health(engine, worker, config):
    memory = psutil.virtual_memory()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    dependencies = {}
    for name, stage in (("ffmpeg", 2), ("ffprobe", 2), ("piper", 2), ("ollama", 4)):
        available = executable(name, config) is not None if name in {"ffmpeg", "ffprobe", "ollama"} else readiness(config)["checks"]["piper"]
        dependencies[name] = {"available": available, "required_from_stage": stage}
    dependencies["voice_pt"] = {"available": voice_model(config) is not None, "required_from_stage": 2}
    dependencies["voice_en"] = {"available": voice_model(config, "EN") is not None, "required_from_stage": 3}
    from services.ollama_client import OllamaClient
    ai = OllamaClient(config).status()
    return {
        "status": "ok" if worker is None or (worker.thread.is_alive() and not worker.last_error) else "degraded",
        "stage": 6, "database": "ok", "sqlite_version": sqlite3.sqlite_version,
        "ai": ai,
        "media": readiness(config, ("PT", "EN")),
        "worker": {"enabled": worker is not None, "running": bool(worker and worker.thread.is_alive()),
                   "error": worker.last_error if worker else None, "concurrency": 1},
        "system": {"os": platform.platform(), "python": platform.python_version(),
                   "cpu_logical": psutil.cpu_count(), "memory_total_gb": round(memory.total / 1024**3, 2),
                   "memory_available_gb": round(memory.available / 1024**3, 2),
                   "disk_free_gb": round(shutil.disk_usage(config.data_dir).free / 1024**3, 2)},
        "dependencies": dependencies,
        "capabilities": {"persistent_queue": True, "project_preparation": True,
                         "render_video": True, "generate_script": True, "generate_topics": True,
                         "batch": True, "bilingual_rendering": True, "visual_library":True, "audio_effects":True},
    }
