import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

from backend.config import Config


def executable(name: str, config: Config) -> Path | None:
    override = getattr(config, f"{name}_path", None)
    if override:
        return override.resolve() if override.is_file() else None
    found = shutil.which(name)
    if found:
        return Path(found)
    extension = ".exe" if os.name == "nt" else ""
    candidates = sorted((config.data_dir / "tools").glob(f"**/{name}{extension}"))
    return candidates[-1].resolve() if candidates else None


def voice_model(config: Config, language="PT") -> Path | None:
    path = (config.voice_path if language == "PT" else config.voice_en_path) or config.data_dir / "voices" / ("pt_BR-faber-medium-aligned.onnx" if language == "PT" else "en_US-ljspeech-high-aligned.onnx")
    return path.resolve() if path.is_file() and Path(str(path) + ".json").is_file() else None


def readiness(config: Config, languages=("PT",)) -> dict:
    checks = {name: executable(name, config) is not None for name in ("ffmpeg", "ffprobe")}
    checks["piper"] = importlib.util.find_spec("piper") is not None
    for language in languages:
        checks[f"voice_{language.lower()}"] = voice_model(config, language) is not None
    checks["svg_renderer"] = importlib.util.find_spec("resvg_py") is not None
    return {"ready": all(checks.values()), "checks": checks}


class MediaError(Exception):
    pass


class Interrupted(MediaError):
    pass


def process_flags():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def contained(root: Path, relative: str) -> Path:
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise MediaError("Caminho de saída fora da pasta de dados.")
    return result
