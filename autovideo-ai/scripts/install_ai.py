"""Portable, verified Ollama installation; no system PATH or admin changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Config
from scripts.install_media import fetch, download
from services.media_tools import executable


def direct_model(config):
    """Use verified GGUF + official `ollama create` when the registry pull stalls."""
    from services.ollama_client import OllamaClient
    client = OllamaClient(config)
    client.ensure_server()
    if client.status()["model_available"]:
        print("Modelo já disponível.", flush=True)
        return
    name, tag = config.ollama_model.split(":", 1)
    if not all(char.isalnum() or char in "-_." for char in name+tag):
        raise RuntimeError("Use um nome simples de modelo para importação direta.")
    base = f"https://registry.ollama.ai/v2/library/{name}"
    manifest = json.loads(fetch(f"{base}/manifests/{tag}"))
    directory = config.data_dir/"ai_downloads"
    directory.mkdir(parents=True, exist_ok=True)
    layer = next(item for item in manifest["layers"] if item["mediaType"].endswith(".model"))
    model = directory/f"{name}-{tag}.gguf"
    if not model.is_file():
        print("Baixando GGUF diretamente do registro oficial, com SHA-256...",flush=True)
        download(f"{base}/blobs/{layer['digest']}", model, layer["digest"].split(":")[1])
    lines = [f'FROM "{model.as_posix()}"', "PARAMETER num_ctx 4096"]
    for item in manifest["layers"]:
        kind = item["mediaType"].rsplit(".",1)[-1]
        if kind not in {"template","license","system","params"}: continue
        data = fetch(f"{base}/blobs/{item['digest']}")
        if hashlib.sha256(data).hexdigest() != item["digest"].split(":")[1]: raise RuntimeError("Hash de metadados inválido.")
        text = data.decode("utf-8")
        if kind == "params":
            for key, values in json.loads(text).items():
                for value in values if isinstance(values,list) else [values]:
                    lines.append(f"PARAMETER {key} {json.dumps(value)}")
        else:
            lines.append(f'{kind.upper()} """{text}"""')
    modelfile = directory/"Modelfile"
    modelfile.write_text("\n".join(lines),encoding="utf-8")
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = config.ollama_url
    print("Importando GGUF local com ollama create...",flush=True)
    result = subprocess.run([str(executable("ollama",config)),"create",config.ollama_model,"-f",str(modelfile)],env=environment,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=600,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if result.returncode: raise RuntimeError(result.stderr[-2000:])
    print("Modelo importado e verificado.",flush=True)


def install():
    config = Config()
    config.prepare_directories()
    if executable("ollama", config):
        print("Ollama já disponível.", flush=True)
        return
    release = json.loads(fetch("https://api.github.com/repos/ollama/ollama/releases/latest"))
    asset = next(item for item in release["assets"] if item["name"] == "ollama-windows-amd64.zip")
    directory = config.data_dir / "tools" / f"ollama-{release['tag_name']}"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory.parent / "ollama-windows-amd64.zip"
    expected = asset.get("digest", "").removeprefix("sha256:")
    if not expected:
        raise RuntimeError("O release não publicou SHA-256; download não será executado sem verificação.")
    print(f"Baixando Ollama {release['tag_name']} ({asset['size']//1_000_000} MB)...", flush=True)
    digest = download(asset["browser_download_url"], archive, expected)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (directory / member.filename).resolve().is_relative_to(directory.resolve()):
                raise RuntimeError("Caminho inválido no pacote Ollama.")
        package.extractall(directory)
    (directory / "installation-receipt.json").write_text(json.dumps({"release": release["tag_name"], "sha256": digest, "source": asset["browser_download_url"]}, indent=2), encoding="utf-8")
    print("Ollama extraído e verificado.", flush=True)


if __name__ == "__main__":
    # Some Windows networks advertise unreachable IPv6 routes for the model CDN.
    # This affects only this installer process; no Windows network setting changes.
    original_resolver = socket.getaddrinfo
    def ipv4_resolver(host, port, family=0, type=0, proto=0, flags=0):
        return original_resolver(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = ipv4_resolver
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--direct-model", action="store_true")
    args = parser.parse_args()
    install()
    if args.direct_model or (os.name == "nt" and not args.download_only):
        direct_model(Config())
    elif not args.download_only:
        from services.ollama_client import OllamaClient
        client = OllamaClient(Config())
        client.ensure_server()
        client.pull()
