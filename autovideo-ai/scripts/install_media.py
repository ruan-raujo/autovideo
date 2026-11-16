"""Install free, local media dependencies without changing the system PATH."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Config
from services.media_tools import executable, readiness


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def download(url, destination, expected=None):
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as target:
        while chunk := source.read(1024*1024):
            target.write(chunk)
            digest.update(chunk)
    if expected and digest.hexdigest().lower() != expected.lower():
        temporary.unlink(missing_ok=True)
        raise RuntimeError("O SHA-256 do arquivo baixado não confere; instalação abortada.")
    temporary.replace(destination)
    return digest.hexdigest()


def install_voice(voices, name, relative):
    model = voices / f"{name}.onnx"
    aligned = voices / f"{name}-aligned.onnx"
    if aligned.is_file() and Path(str(aligned)+".json").is_file():
        return
    if not model.is_file() or not Path(str(model)+".json").is_file():
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{relative}/"
        tree = json.loads(fetch(f"https://huggingface.co/api/models/rhasspy/piper-voices/tree/main/{relative}"))
        expected = next(item["lfs"]["oid"] for item in tree if item["path"].endswith(model.name))
        print(f"Baixando voz {name}...", flush=True)
        download(base+model.name, model, expected)
        download(base+model.name+".json", Path(str(model)+".json"))
        download(base+"MODEL_CARD", voices/f"MODEL_CARD-{name}.md")
    import onnx
    from piper.patch_voice_with_alignment import add_alignment_output
    data = onnx.load(str(model))
    add_alignment_output(data)
    temporary = aligned.with_suffix(".onnx.part")
    onnx.save(data, str(temporary))
    temporary.replace(aligned)
    shutil.copyfile(str(model)+".json", str(aligned)+".json")


def main():
    config = Config()
    config.prepare_directories()
    tools, voices = config.data_dir / "tools", config.data_dir / "voices"
    tools.mkdir(exist_ok=True)
    voices.mkdir(exist_ok=True)
    receipt = {}
    if executable("ffmpeg", config) is None or executable("ffprobe", config) is None:
        print("Baixando FFmpeg/FFprobe para uso local...", flush=True)
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        expected = re.search(r"[a-fA-F0-9]{64}", fetch(url + ".sha256").decode()).group(0)
        archive = tools / "ffmpeg-release-essentials.zip"
        receipt["ffmpeg_sha256"] = download(url, archive, expected)
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                target = (tools / member.filename).resolve()
                if not target.is_relative_to(tools.resolve()):
                    raise RuntimeError("O pacote de mídia contém um caminho inválido.")
            package.extractall(tools)
    model = voices / "pt_BR-faber-medium.onnx"
    if not model.is_file() or not Path(str(model)+".json").is_file():
        print("Baixando voz brasileira faber (aproximadamente 64 MB)...", flush=True)
        base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/"
        tree = json.loads(fetch("https://huggingface.co/api/models/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium"))
        expected = next(item["lfs"]["oid"] for item in tree if item["path"].endswith(model.name))
        receipt["voice_sha256"] = download(base + model.name, model, expected)
        download(base + model.name + ".json", Path(str(model)+".json"))
        download(base + "MODEL_CARD", voices / "MODEL_CARD-faber.md")
    aligned = voices / "pt_BR-faber-medium-aligned.onnx"
    if not aligned.is_file():
        print("Preparando alinhamento temporal da voz...", flush=True)
        import onnx
        from piper.patch_voice_with_alignment import add_alignment_output
        data = onnx.load(str(model))
        add_alignment_output(data)
        temporary = aligned.with_suffix(".onnx.part")
        onnx.save(data, str(temporary))
        temporary.replace(aligned)
    if not Path(str(aligned)+".json").is_file():
        shutil.copyfile(str(model)+".json", str(aligned)+".json")
    install_voice(voices, "en_US-ljspeech-high", "en/en_US/ljspeech/high")
    status = readiness(config, ("PT", "EN"))
    if not status["ready"]:
        raise RuntimeError(f"Instalação incompleta: {status['checks']}")
    if receipt:
        receipt["sources"] = ["https://www.gyan.dev/ffmpeg/builds/", "https://huggingface.co/rhasspy/piper-voices"]
        (tools / "installation-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print("Mídia pronta. Tudo funciona localmente após estes downloads.")
    print("Reinicie start.bat se ele já estiver aberto.")


if __name__ == "__main__":
    main()
