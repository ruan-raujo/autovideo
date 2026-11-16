"""Local image library: bounded decoding, normalized PNGs and contained paths."""
import base64
import binascii
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from backend.config import ROOT
from models.entities import Script, VisualAsset
from services.queue import QueueError

BUILTINS = ("earth", "mars", "sun", "moon", "person", "tree", "building", "snowflake", "rocket", "vent", "microbe")


class AssetLibrary:
    def __init__(self, sessions, data_dir):
        self.sessions, self.folder = sessions, data_dir / "assets"
        self.folder.mkdir(exist_ok=True, parents=True)
        with sessions.begin() as session:
            for name in BUILTINS:
                if not session.get(VisualAsset, name):
                    session.add(VisualAsset(id=name, name=name, file_path=f"builtin:{name}", license="CC0-1.0 — AutoVideo AI", kind="svg"))

    def list(self):
        with self.sessions() as session:
            return [{"id":a.id,"name":a.name,"license":a.license,"kind":a.kind,"builtin":a.id in BUILTINS,
                     "image_url":f"/api/assets/{a.id}/image"} for a in session.scalars(select(VisualAsset).order_by(VisualAsset.name))]

    def path(self, asset_id):
        with self.sessions() as session:
            asset = session.get(VisualAsset, asset_id)
            if not asset:
                raise QueueError("Recurso visual não encontrado.",404)
            if asset_id in BUILTINS:
                return ROOT / "assets/svg" / f"{asset_id}.svg"
            path = (self.folder / f"{asset_id}.png").resolve()
            if not path.is_relative_to(self.folder.resolve()) or not path.is_file():
                raise QueueError("Arquivo visual indisponível.",404)
            return path

    def upload(self, payload):
        try:
            raw = base64.b64decode(payload.image_base64, validate=True)
            if len(raw)>2_000_000:
                raise ValueError("Use uma imagem de até 2 MB.")
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ("PNG","JPEG") or max(image.size)>4096 or image.width*image.height>8_000_000:
                    raise ValueError("Use PNG/JPEG de até 4096 px e 8 megapixels.")
                image.load()
                normalized = image.convert("RGBA")
                normalized.thumbnail((1024,1024),Image.Resampling.LANCZOS)
        except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise QueueError(f"Imagem inválida: {error}",422) from error
        asset_id = "asset_"+uuid4().hex
        path = self.folder / f"{asset_id}.png"
        normalized.save(path,"PNG")
        try:
            with self.sessions.begin() as session:
                session.add(VisualAsset(id=asset_id,name=payload.name.strip(),license=payload.license.strip(),file_path=path.name,kind="png"))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return next(item for item in self.list() if item["id"]==asset_id)

    def update(self, asset_id, payload):
        if asset_id in BUILTINS:
            raise QueueError("Os recursos incluídos são somente leitura.")
        with self.sessions.begin() as session:
            asset = session.get(VisualAsset,asset_id)
            if not asset:
                raise QueueError("Recurso visual não encontrado.",404)
            asset.name, asset.license = payload.name.strip(), payload.license.strip()

    def delete(self, asset_id):
        path = self.path(asset_id)
        if asset_id in BUILTINS:
            raise QueueError("Os recursos incluídos são somente leitura.")
        with self.sessions.begin() as session:
            for script in session.scalars(select(Script)):
                if any(element.get("asset")==asset_id for scene in script.content["scenes"] for element in scene.get("elements",[])):
                    raise QueueError("O recurso está em uso em um roteiro salvo.")
            session.delete(session.get(VisualAsset,asset_id))
        path.unlink(missing_ok=True)
