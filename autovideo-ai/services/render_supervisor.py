"""Supervise a bounded media process, cooperatively honoring queue controls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil

from backend.config import ROOT
from services.media_tools import Interrupted, MediaError, executable, process_flags, voice_model


def kill_tree(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs(children+[parent], timeout=10)
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=15)


def render_project(config, job_id, token, script, settings, checkpoint, update):
    scripts = script if "PT" in script or "EN" in script else {script["language"]: script}
    request = {"job_id": job_id, "scripts": scripts, "settings": settings.model_dump(),
               "ffmpeg": str(executable("ffmpeg", config)), "ffprobe": str(executable("ffprobe", config)),
               "voice": str(voice_model(config)), "owner_pid": os.getpid(), "owner_created": psutil.Process().create_time()}
    request["voices"] = {language: str(voice_model(config, language)) for language in scripts}
    request["asset_folder"] = str(config.data_dir / "assets")
    for script_data in scripts.values():
        for scene in script_data["scenes"]:
            for item in scene.get("elements",[]):
                if item["asset"].startswith("asset_") and not (config.data_dir / "assets" / f"{item['asset']}.png").is_file():
                    raise MediaError(f"Recurso visual indisponível: {item['asset']}.")
    return run_job_process(config, job_id, token, request, settings, checkpoint, update)


def run_job_process(config, job_id, token, request, settings, checkpoint, update, module="services.render_job"):
    workspace = config.data_dir / "temp" / f"render_{token}"
    workspace.mkdir(parents=True, exist_ok=False)
    request.update({"owner_pid":os.getpid(),"owner_created":psutil.Process().create_time(),"settings":settings.model_dump()})
    (workspace / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    environment = os.environ.copy()
    environment["OMP_NUM_THREADS"] = str(settings.cpu_threads)
    environment["OPENBLAS_NUM_THREADS"] = str(settings.cpu_threads)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    try:
        with (workspace / "process.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-m", module, str(workspace)], cwd=ROOT, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, **process_flags())
            start, previous = time.monotonic(), None
            try:
                while process.poll() is None:
                    checkpoint()
                    try:
                        parent = psutil.Process(process.pid)
                        memory = sum(item.memory_info().rss for item in [parent]+parent.children(recursive=True) if item.is_running())
                        if memory > settings.render_memory_mb * 1024**2:
                            raise MediaError(f"A renderização excedeu o limite de {settings.render_memory_mb} MB. Aumente o limite nas configurações ou simplifique as cenas.")
                    except psutil.NoSuchProcess:
                        pass
                    if time.monotonic()-start > 1800:
                        raise MediaError("A renderização excedeu 30 minutos. Simplifique as cenas e tente retomar.")
                    try:
                        progress = json.loads((workspace / "progress.json").read_text(encoding="utf-8"))
                        if progress != previous:
                            update(progress)
                            previous = progress
                    except (OSError, json.JSONDecodeError):
                        pass
                    time.sleep(.2)
                checkpoint()
                if process.returncode:
                    failure_path = workspace / "failure.json"
                    if failure_path.is_file():
                        raise MediaError(json.loads(failure_path.read_text(encoding="utf-8"))["message"])
                    raise MediaError("O processo de mídia encerrou inesperadamente. Consulte o log local.")
            finally:
                if process.poll() is None:
                    kill_tree(process)
        result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
        return workspace, result
    except Exception:
        for source in ("render.log", "process.log"):
            path = workspace / source
            if path.is_file():
                content = path.read_bytes()[-200_000:]
                (config.data_dir / "logs" / f"{job_id}-{source}").write_bytes(content)
        # The directory is generated here from a UUID token, contained in data_dir/temp.
        if workspace.resolve().is_relative_to((config.data_dir / "temp").resolve()):
            shutil.rmtree(workspace)
        raise
