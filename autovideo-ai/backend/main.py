from contextlib import asynccontextmanager
import logging
from logging.handlers import RotatingFileHandler
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.config import Config, ROOT
from database.session import open_database
from models.schemas import CreateStory, JobList, JobResponse, QueueSettings, ScriptInput, RenderRequest, GenerateScriptRequest, GenerateTopicsRequest, BatchRequest, AssetUpload, AssetMetadata, VIDEO_SPEC
from services.diagnostics import health
from services.process_lock import ProcessLock
from services.queue import QueueError, QueueService, Worker


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()

    @asynccontextmanager
    async def lifespan(application):
        config.prepare_directories()
        lock = ProcessLock(config.data_dir / "database" / "server.lock")
        lock.acquire()
        handler = RotatingFileHandler(config.data_dir / "logs" / "autovideo.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        app_logger = logging.getLogger("services")
        app_logger.setLevel(logging.INFO)
        app_logger.addHandler(handler)
        worker = None
        engine = None
        try:
            engine, sessions = open_database(config)
            queue = QueueService(sessions, config.data_dir, config)
            application.state.queue = queue
            from services.assets import AssetLibrary
            application.state.assets = AssetLibrary(sessions, config.data_dir)
            application.state.engine = engine
            if config.worker_enabled:
                worker = Worker(queue)
                worker.start()
            application.state.worker = worker
            yield
        finally:
            if worker:
                worker.stop()
            if engine:
                engine.dispose()
            app_logger.removeHandler(handler)
            handler.close()
            lock.release()

    application = FastAPI(
        title="AutoVideo AI", version="1.0.0", lifespan=lifespan,
        description="Produção local PT/EN: Ollama, Piper, animação 2D, lotes e MP4 de 80 segundos validados integralmente.",
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @application.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Acesso permitido apenas pela interface local da mesma origem."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Requisição externa bloqueada."}, status_code=403)
            if request.method == "PUT" or request.url.path == "/api/videos":
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    return JSONResponse({"detail": "Envie o corpo como application/json."}, status_code=415)
            # Bound actual bytes, including bodies sent without Content-Length.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > (2_900_000 if request.url.path == "/api/assets" else 65_536 if request.url.path.endswith("/script") else 16_384):
                    return JSONResponse({"detail": "Corpo da requisição muito grande."}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            if not request.url.path.startswith(("/docs", "/redoc")) else
            "default-src 'self' https://cdn.jsdelivr.net https://fastapi.tiangolo.com; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
        )
        return response

    @application.exception_handler(QueueError)
    async def queue_error(_, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    @application.post("/api/videos", response_model=JobResponse, status_code=202, tags=["Trabalhos"])
    def create_video(payload: CreateStory):
        """Salva o tema. Depois edite o roteiro e chame /render para gerar o MP4."""
        return application.state.queue.create(payload.topic, payload.automatic)

    @application.post("/api/videos/batch", status_code=202, tags=["Lotes"])
    def batch(payload: BatchRequest):
        return application.state.queue.create_batch(payload)

    @application.get("/api/batches", tags=["Lotes"])
    def list_batches():
        return {"items":application.state.queue.list_batches()}

    @application.get("/api/batches/{batch_id}", tags=["Lotes"])
    def get_batch(batch_id: UUID):
        return application.state.queue.get_batch(str(batch_id))

    @application.post("/api/batches/{batch_id}/{action}", tags=["Lotes"])
    def control_batch(batch_id: UUID, action: Literal["pause","resume","cancel"]):
        return application.state.queue.control_batch(str(batch_id),action)

    @application.post("/api/topics/generate", status_code=202, tags=["IA local"])
    def generate_topic(payload: GenerateTopicsRequest | None = None):
        payload = payload or GenerateTopicsRequest()
        return application.state.queue.request_topics(payload.count, payload.seed_topic)

    @application.get("/api/topics/tasks/{request_id}", tags=["IA local"])
    def get_topic_request(request_id: UUID):
        return application.state.queue.get_topics(str(request_id))

    @application.post("/api/topics/tasks/{request_id}/cancel", tags=["IA local"])
    def cancel_topic_request(request_id: UUID):
        return application.state.queue.cancel_topics(str(request_id))

    @application.post("/api/videos/{job_id}/generate-script", response_model=JobResponse, status_code=202, tags=["IA local"])
    def generate_script(job_id: UUID, payload: GenerateScriptRequest | None = None):
        return application.state.queue.request_generation(str(job_id), (payload or GenerateScriptRequest()).auto_render)

    @application.get("/api/videos", response_model=JobList, tags=["Trabalhos"])
    def list_videos(
        limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
        status: Literal["queued", "preparing", "awaiting_renderer", "paused", "cancelled", "failed", "render_queued", "synthesizing", "rendering", "validating", "completed"] | None = None,
    ):
        return application.state.queue.list(limit, offset, status)

    @application.get("/api/videos/{job_id}", response_model=JobResponse, tags=["Trabalhos"])
    def get_video(job_id: UUID):
        return application.state.queue.get(str(job_id))

    @application.post("/api/videos/{job_id}/pause", response_model=JobResponse, tags=["Trabalhos"])
    def pause(job_id: UUID):
        return application.state.queue.control(str(job_id), "pause")

    @application.post("/api/videos/{job_id}/resume", response_model=JobResponse, tags=["Trabalhos"])
    def resume(job_id: UUID):
        return application.state.queue.control(str(job_id), "resume")

    @application.post("/api/videos/{job_id}/cancel", response_model=JobResponse, tags=["Trabalhos"])
    def cancel(job_id: UUID):
        return application.state.queue.control(str(job_id), "cancel")

    @application.get("/api/videos/{job_id}/download/{language}", tags=["Mídia"])
    def download(job_id: UUID, language: Literal["PT", "EN"]):
        application.state.queue.get(str(job_id))
        path = application.state.queue.media_path(str(job_id), language=language)
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @application.get("/api/videos/{job_id}/preview", tags=["Mídia"])
    def preview(job_id: UUID, language: Literal["PT", "EN"] = "PT"):
        return FileResponse(application.state.queue.media_path(str(job_id), language=language), media_type="video/mp4", content_disposition_type="inline")

    @application.get("/api/videos/{job_id}/subtitles", tags=["Mídia"])
    def subtitles(job_id: UUID, language: Literal["PT", "EN"] = "PT"):
        return FileResponse(application.state.queue.media_path(str(job_id), "subtitles", language), filename=f"legendas_{language}.srt", media_type="application/x-subrip")

    @application.get("/api/videos/{job_id}/validation", tags=["Mídia"])
    def validation(job_id: UUID, language: Literal["PT", "EN"] = "PT"):
        return FileResponse(application.state.queue.media_path(str(job_id), "validation", language), media_type="application/json")

    @application.get("/api/examples/sun", tags=["Roteiros"])
    def example():
        import json
        data = json.loads((ROOT / "assets/examples/sun-disappears.json").read_text(encoding="utf-8"))
        english = json.loads((ROOT / "assets/examples/sun-disappears-en.json").read_text(encoding="utf-8"))
        for original, translated in zip(data["script"]["scenes"], english["scenes"], strict=True):
            for key in ("background", "elements", "camera"):
                if key in original:
                    translated[key] = original[key]
        data["scripts"] = {"PT": data["script"], "EN": english}
        return data

    @application.get("/api/videos/{job_id}/script", tags=["Roteiros"])
    def get_script(job_id: UUID, language: Literal["PT", "EN"] = "PT"):
        return {"script": application.state.queue.script(str(job_id), language)}

    @application.put("/api/videos/{job_id}/script", response_model=ScriptInput, tags=["Roteiros"])
    def put_script(job_id: UUID, payload: ScriptInput):
        return application.state.queue.save_script(str(job_id), payload)

    @application.post("/api/videos/{job_id}/render", response_model=JobResponse, status_code=202, tags=["Mídia"])
    def render(job_id: UUID, payload: RenderRequest | None = None):
        return application.state.queue.request_render(str(job_id), payload.languages if payload else ("PT",))

    @application.get("/api/settings", tags=["Configurações"])
    def get_settings():
        return {"queue": application.state.queue.get_settings(), "video_specification": VIDEO_SPEC,
                "data_dir": str(config.data_dir), "stage": 6}

    @application.get("/api/assets", tags=["Biblioteca"])
    def assets():
        return {"items":application.state.assets.list()}

    @application.post("/api/assets", status_code=201, tags=["Biblioteca"])
    def upload_asset(payload: AssetUpload):
        return application.state.assets.upload(payload)

    @application.get("/api/assets/{asset_id}/image", tags=["Biblioteca"])
    def asset_image(asset_id: str):
        return FileResponse(application.state.assets.path(asset_id))

    @application.put("/api/assets/{asset_id}", tags=["Biblioteca"])
    def update_asset(asset_id: str, payload: AssetMetadata):
        application.state.assets.update(asset_id,payload)
        return {"updated":True}

    @application.delete("/api/assets/{asset_id}", tags=["Biblioteca"])
    def delete_asset(asset_id: str):
        application.state.assets.delete(asset_id)
        return {"deleted":True}

    @application.put("/api/settings", response_model=QueueSettings, tags=["Configurações"])
    def put_settings(payload: QueueSettings):
        return application.state.queue.set_settings(payload)

    @application.get("/api/health", tags=["Diagnóstico"])
    def get_health():
        return health(application.state.engine, application.state.worker, config)

    application.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return application


app = create_app()
