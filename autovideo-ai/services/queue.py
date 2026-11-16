import json
import logging
import os
import threading
import unicodedata
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from backend.config import Config
from models.entities import AIRequest, Batch, GenerationEvent, Job, Scene, Script, Setting, Story, Video, new_id, now
from models.schemas import JobResponse, QueueSettings, ScriptInput, VIDEO_SPEC
from services.media_tools import Interrupted, MediaError, contained, readiness

logger = logging.getLogger(__name__)


class QueueError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        self.message, self.status_code = message, status_code


def topic_key(topic: str) -> str:
    text = unicodedata.normalize("NFKD", topic.casefold())
    return "".join(char for char in text if char.isalnum())


def record(session, job: Job, status: str, message: str) -> None:
    job.status, job.message, job.updated_at = status, message, now()
    session.add(GenerationEvent(job_id=job.id, status=status, message=message))


class QueueService:
    def __init__(self, sessions, data_dir: Path, config=None):
        self.sessions, self.data_dir = sessions, data_dir
        self.config = config or Config(data_dir=data_dir)
        self.interrupt_event = threading.Event()

    def get_settings(self) -> QueueSettings:
        with self.sessions() as session:
            setting = session.get(Setting, "queue")
            return QueueSettings.model_validate(setting.value) if setting else QueueSettings()

    def set_settings(self, settings: QueueSettings) -> QueueSettings:
        with self.sessions.begin() as session:
            session.merge(Setting(key="queue", value=settings.model_dump()))
        return settings

    def create(self, topic: str, automatic=False) -> JobResponse:
        try:
            with self.sessions.begin() as session:
                story = Story(topic=topic, topic_key=topic_key(topic))
                session.add(story)
                session.flush()
                job = Job(story_id=story.id, task="automatic" if automatic else "prepare", generation_options={"auto_render":True} if automatic else None)
                session.add(job)
                session.flush()
                record(session, job, "queued", "Tema salvo. Aguardando preparação local.")
                job_id = job.id
        except IntegrityError as exc:
            raise QueueError("Este tema já existe no histórico. Escolha um tema diferente.") from exc
        logger.info("Trabalho criado: %s", job_id)
        return self.get(job_id)

    def _response(self, session, job, *, detail=False):
        story = session.get(Story, job.story_id)
        script_languages = list(session.scalars(select(Script.language).where(Script.story_id == story.id)))
        video_languages = list(session.scalars(select(Video.language).where(Video.story_id == story.id))) if job.status == "completed" else []
        events = []
        if detail:
            events = [
                {"status": e.status, "message": e.message, "created_at": e.created_at}
                for e in session.scalars(select(GenerationEvent).where(
                    GenerationEvent.job_id == job.id
                ).order_by(GenerationEvent.id))
            ]
        return JobResponse(
            **{key: getattr(job, key) for key in (
                "id", "story_id", "status", "progress", "message", "error",
                "attempts", "created_at", "updated_at",
            )}, topic=story.topic, preparation_complete=bool(job.manifest_path), events=events,
            script_available="PT" in script_languages,
            video_available=bool(video_languages),
            script_languages=[lang for lang in ("PT", "EN") if lang in script_languages],
            video_languages=[lang for lang in ("PT", "EN") if lang in video_languages],
            task=job.task,
            batch_id=job.batch_id,
        )

    def get(self, job_id: str) -> JobResponse:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise QueueError("Trabalho não encontrado.", 404)
            return self._response(session, job, detail=True)

    def list(self, limit=50, offset=0, status=None):
        with self.sessions() as session:
            query = select(Job)
            if status:
                query = query.where(Job.status == status)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            jobs = session.scalars(query.order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset))
            counts = dict(session.execute(select(Job.status, func.count()).group_by(Job.status)).all())
            return {"items": [self._response(session, job) for job in jobs], "total": total, "counts": counts}

    def control(self, job_id: str, action: str) -> JobResponse:
        allowed = {
            "pause": ({"queued", "preparing", "render_queued", "synthesizing", "rendering", "validating"}, "paused", "Trabalho pausado pelo usuário. A renderização será reiniciada ao retomar."),
            "resume": ({"paused", "failed"}, "queued", "Trabalho reenviado para preparação."),
            "cancel": ({"queued", "preparing", "paused", "awaiting_renderer", "failed", "render_queued", "synthesizing", "rendering", "validating"}, "cancelled", "Trabalho cancelado pelo usuário."),
        }
        sources, target, message = allowed[action]
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise QueueError("Trabalho não encontrado.", 404)
            if job.status not in sources:
                raise QueueError("Esta ação não está disponível para o estado atual do trabalho.")
            if action == "resume":
                job.error, job.progress = None, 0
                if job.task in {"render", "generate"}:
                    job.render_token = new_id()
                if job.task == "render":
                    target, job.render_token = "render_queued", new_id()
            record(session, job, target, message)
        return self.get(job_id)

    def recover(self) -> int:
        # Only our UUID-named files may be cleaned; unrelated files are preserved.
        from uuid import UUID
        for path in (self.data_dir / "temp").glob("*.json.tmp"):
            try:
                UUID(path.name.removesuffix(".json.tmp"))
            except ValueError:
                continue
            path.unlink(missing_ok=True)
        for directory in (self.data_dir / "temp").glob("render_*"):
            try:
                UUID(directory.name.removeprefix("render_"))
            except ValueError:
                continue
            if directory.is_dir() and not directory.is_symlink() and directory.resolve().is_relative_to((self.data_dir / "temp").resolve()):
                import shutil
                import time
                for attempt in range(8):
                    try:
                        shutil.rmtree(directory)
                        break
                    except PermissionError:
                        time.sleep(.25)
                else:
                    logger.warning("Temporário ainda em uso; limpeza adiada: %s", directory.name)
        with self.sessions.begin() as session:
            for request in session.scalars(select(AIRequest).where(AIRequest.status == "running")):
                request.status, request.progress = "queued", 0
            jobs = list(session.scalars(select(Job).where(Job.status.in_(["preparing", "synthesizing", "rendering", "validating"]))))
            for job in jobs:
                job.progress = 0
                if job.task in {"render", "generate"}:
                    job.render_token = new_id()
                record(session, job, "render_queued" if job.task == "render" else "queued", "Trabalho interrompido; retomada após reinício.")
            return len(jobs)

    def claim(self) -> str | None:
        with self.sessions.begin() as session:
            job = session.scalar(select(Job).where(Job.status.in_(["queued", "render_queued"])).order_by(Job.updated_at, Job.id).limit(1))
            if job is None:
                return None
            job.attempts += 1
            message = "Carregando a voz local." if job.task == "render" else ("Gerando roteiros com Ollama local." if job.task == "generate" else "Validando tema e gravando o projeto em JSON.")
            record(session, job, "synthesizing" if job.task == "render" else "preparing", message)
            return job.id

    def prepare(self, job_id: str) -> None:
        temporary = self.data_dir / "temp" / f"{job_id}.json.tmp"
        try:
            # All paths derive from a server-generated UUID, never from a topic.
            with self.sessions() as session:
                job = session.get(Job, job_id)
                if job.status != "preparing":
                    return
                story = session.get(Story, job.story_id)
                manifest = {
                    "schema_version": 1, "job_id": job.id, "story_id": story.id,
                    "topic": story.topic, "specification": VIDEO_SPEC,
                    "scripts": {}, "scenes": [], "created_at": story.created_at,
                    "preparation": "complete", "rendering": "awaiting_script",
                }
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            with self.sessions.begin() as session:
                job = session.get(Job, job_id)
                if job.status != "preparing":
                    return
                output = self.data_dir / "output" / job.story_id
                output.mkdir(parents=True, exist_ok=True)
                target = output / "project.json"
                os.replace(temporary, target)
                job.manifest_path = str(target.relative_to(self.data_dir))
                # Preparation is complete; no media progress is claimed.
                job.progress = 0
                record(session, job, "awaiting_renderer", "Projeto preparado. Edite o roteiro e solicite a geração do vídeo PT.")
                if job.task == "automatic":
                    job.task, job.render_token = "generate", new_id()
                    record(session, job, "queued", "Projeto preparado. Aguardando geração dos roteiros locais PT/EN.")
            logger.info("Projeto preparado: %s", job_id)
        except Exception:
            logger.exception("Falha na preparação: %s", job_id)
            with self.sessions.begin() as session:
                job = session.get(Job, job_id)
                if job and job.status == "preparing":
                    job.error = "Falha ao preparar o projeto. Consulte o log local e tente retomar."
                    record(session, job, "failed", job.error)
        finally:
            temporary.unlink(missing_ok=True)

    def script(self, job_id, language="PT"):
        with self.sessions() as session:
            job = session.get(Job, job_id)
            if not job:
                raise QueueError("Trabalho não encontrado.", 404)
            script = session.scalar(select(Script).where(Script.story_id == job.story_id, Script.language == language))
            return script.content if script else None

    def save_script(self, job_id, payload: ScriptInput):
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if not job:
                raise QueueError("Trabalho não encontrado.", 404)
            if job.status not in {"awaiting_renderer", "failed", "paused", "completed"}:
                raise QueueError("O roteiro só pode ser editado após a preparação ou com o trabalho pausado/com erro.")
            if not job.manifest_path:
                raise QueueError("O projeto ainda não foi preparado. Retome a preparação antes de editar o roteiro.")
            script = session.scalar(select(Script).where(Script.story_id == job.story_id, Script.language == payload.language))
            if script is None:
                script = Script(story_id=job.story_id, language=payload.language, content=payload.model_dump())
                session.add(script)
                session.flush()
            else:
                session.execute(delete(Scene).where(Scene.script_id == script.id))
                script.content = payload.model_dump()
            for index, scene in enumerate(payload.scenes):
                session.add(Scene(script_id=script.id, position=index, content=scene.model_dump()))
            if job.status == "completed":
                record(session, job, "awaiting_renderer", "Roteiro alterado; gere novamente os vídeos para publicar a revisão.")
                job.progress = 0
                session.execute(delete(Video).where(Video.story_id == job.story_id))
            session.add(GenerationEvent(job_id=job.id, status=job.status, message=f"Roteiro {payload.language} salvo e validado: 2400 quadros / 80 segundos."))
        return payload

    def request_render(self, job_id, languages=("PT",)):
        languages = list(languages)
        media = readiness(self.config) if languages == ["PT"] else readiness(self.config, languages)
        if not media["ready"]:
            missing = ", ".join(name for name, available in media["checks"].items() if not available)
            raise QueueError(f"Dependências de mídia ausentes: {missing}. Execute instalar_midia.bat.", 503)
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if not job:
                raise QueueError("Trabalho não encontrado.", 404)
            if job.status not in {"awaiting_renderer", "failed", "paused"}:
                raise QueueError("A geração só pode ser iniciada após a preparação ou a partir de um trabalho pausado/com erro.")
            if not job.manifest_path:
                raise QueueError("O projeto ainda não foi preparado. Retome a preparação antes de gerar o vídeo.")
            scripts = {script.language: script for script in session.scalars(select(Script).where(Script.story_id == job.story_id))}
            if any(language not in scripts for language in languages):
                raise QueueError("Salve os roteiros dos idiomas solicitados antes de gerar os vídeos.")
            for language in languages:
                ScriptInput.model_validate(scripts[language].content)
            if "PT" in scripts and "EN" in scripts:
                pt, en = scripts["PT"].content, scripts["EN"].content
                if len(pt["scenes"]) != len(en["scenes"]):
                    raise QueueError("PT e EN devem ter o mesmo número de cenas para compartilhar o plano visual.")
                synchronized = json.loads(json.dumps(en))
                for original, translated in zip(pt["scenes"], synchronized["scenes"], strict=True):
                    for key in ("background", "elements", "camera", "transition", "transition_frames"):
                        translated[key] = original[key]
                scripts["EN"].content = synchronized
                session.execute(delete(Scene).where(Scene.script_id == scripts["EN"].id))
                for index, scene in enumerate(synchronized["scenes"]):
                    session.add(Scene(script_id=scripts["EN"].id,position=index,content=scene))
            job.task, job.render_token, job.progress, job.error = "render", new_id(), 0, None
            job.render_languages = languages
            session.execute(delete(Video).where(Video.story_id == job.story_id))
            record(session, job, "render_queued", f"Vídeos {'/'.join(languages)} adicionados à fila local.")
        return self.get(job_id)

    def media_path(self, job_id, kind="video", language="PT"):
        with self.sessions() as session:
            job = session.get(Job, job_id)
            if not job:
                raise QueueError("Trabalho não encontrado.", 404)
            video = session.scalar(select(Video).where(Video.story_id == job.story_id, Video.language == language))
            if job.status != "completed" or not video:
                raise QueueError("Este trabalho ainda não possui um vídeo validado.")
            try:
                file = contained(self.data_dir, video.file_path)
                if kind == "subtitles":
                    file = file.parent / "subtitles.srt"
                elif kind == "validation":
                    file = file.parent / "validation.json"
            except MediaError as error:
                raise QueueError(str(error), 404) from error
            if not file.is_file():
                raise QueueError("Arquivo não encontrado na pasta de dados.", 404)
            return file

    def render(self, job_id):
        from services.render_supervisor import render_project
        with self.sessions() as session:
            job = session.get(Job, job_id)
            token, story_id, languages = job.render_token, job.story_id, job.render_languages
        workspace = None
        scripts_payload = {lang: self.script(job_id, lang) for lang in languages}
        try:
            if not readiness(self.config, languages)["ready"]:
                raise MediaError("Uma dependência de mídia não está mais disponível. Execute instalar_midia.bat e tente retomar.")
            def checkpoint():
                with self.sessions() as session:
                    current = session.get(Job, job_id)
                    if self.interrupt_event.is_set() or current.render_token != token or current.status not in {"synthesizing", "rendering", "validating"}:
                        raise Interrupted("Processamento interrompido pelo controle da fila.")

            def update(payload):
                with self.sessions.begin() as session:
                    current = session.get(Job, job_id)
                    if current.render_token == token and current.status in {"synthesizing", "rendering", "validating"}:
                        if current.status != payload["state"]:
                            record(session, current, payload["state"], payload["message"])
                        current.progress = payload["progress"]
                        current.message, current.updated_at = payload["message"], now()

            checkpoint()
            workspace, result = render_project(self.config, job_id, token, scripts_payload, self.get_settings(), checkpoint, update)
            checkpoint()
            destination = self.data_dir / "output" / story_id / token
            with self.sessions.begin() as session:
                current = session.get(Job, job_id)
                if current.render_token != token or current.status not in {"synthesizing", "rendering", "validating"}:
                    raise Interrupted("Trabalho interrompido antes da publicação do vídeo.")
                workspace.rename(destination)
                video_paths = {}
                for language, output in result["videos"].items():
                    video = session.scalar(select(Video).where(Video.story_id == story_id, Video.language == language))
                    if video is None:
                        video = Video(story_id=story_id, language=language, file_path="", metadata_json={})
                        session.add(video)
                    video.file_path = str((destination / output["filename"]).relative_to(self.data_dir))
                    video.metadata_json = output["metadata"]
                    video_paths[language] = video.file_path
                manifest_path = contained(self.data_dir, current.manifest_path)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.update({"scripts": scripts_payload, "scenes": next(iter(scripts_payload.values()))["scenes"], "rendering": "validated", "videos": video_paths, "produced_languages": list(video_paths)})
                # Manifest is informational; the transactional Video row gates access.
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                current.progress, current.error = 100, None
                record(session, current, "completed", f"Vídeos {'/'.join(languages)} validados: 80 segundos, 2400 quadros, áudio e legendas.")
        except Interrupted:
            logger.info("Renderização interrompida: %s", job_id)
        except Exception as error:
            logger.exception("Falha na renderização: %s", job_id)
            with self.sessions.begin() as session:
                current = session.get(Job, job_id)
                if current.render_token == token and current.status in {"synthesizing", "rendering", "validating"}:
                    current.error = str(error)[:600] if isinstance(error, MediaError) else "Falha na renderização. Consulte o log local."
                    record(session, current, "failed", current.error)
        finally:
            if workspace and workspace.exists() and workspace.resolve().is_relative_to((self.data_dir / "temp").resolve()):
                import shutil
                shutil.rmtree(workspace)

    def topic_history(self):
        with self.sessions() as session:
            return [topic for topic in session.scalars(select(Story.topic).order_by(Story.created_at)) if not topic.startswith("Tema automático pendente ")]

    def create_batch(self, payload):
        try:
            with self.sessions.begin() as session:
                batch = Batch(requested_count=payload.count, automatic=payload.automatic)
                session.add(batch)
                session.flush()
                batch_id = batch.id
                for index in range(payload.count):
                    topic = payload.topics[index] if payload.topics else f"Tema automático pendente {batch_id[:8]}-{index+1}"
                    story = Story(topic=topic, topic_key=topic_key(topic))
                    session.add(story)
                    session.flush()
                    job = Job(story_id=story.id, batch_id=batch.id, task="automatic" if payload.automatic else "prepare",
                              generation_options={"auto_render":True,"auto_topic":payload.topics is None,"seed_topic":payload.topic} if payload.automatic else None)
                    session.add(job)
                    session.flush()
                    record(session, job, "queued", "História adicionada ao lote; aguardando processamento local.")
        except IntegrityError as error:
            raise QueueError("Um tema do lote já existe no histórico ou está repetido. O lote inteiro foi recusado.") from error
        return self.get_batch(batch_id)

    def get_batch(self, batch_id):
        with self.sessions() as session:
            batch = session.get(Batch, batch_id)
            if not batch: raise QueueError("Lote não encontrado.",404)
            jobs = list(session.scalars(select(Job).where(Job.batch_id==batch_id).order_by(Job.created_at,Job.id)))
            counts = {}
            for job in jobs: counts[job.status] = counts.get(job.status,0)+1
            terminal = sum(counts.get(state,0) for state in ("completed","cancelled","failed"))
            status = "running"
            if counts.get("completed",0) == len(jobs): status = "completed"
            elif counts.get("cancelled",0) == len(jobs): status = "cancelled"
            elif terminal == len(jobs): status = "partial"
            elif all(job.status in {"paused","completed","cancelled","failed"} for job in jobs): status = "paused"
            elif all(job.status in {"awaiting_renderer","completed","cancelled","failed"} for job in jobs): status = "awaiting_input"
            return {"id":batch.id,"batch_id":batch.id,"created_at":batch.created_at,"automatic":batch.automatic,
                    "count":batch.requested_count,"status":status,"counts":counts,"progress":sum(job.progress for job in jobs)//max(1,len(jobs)),
                    "items":[self._response(session,job) for job in jobs]}

    def list_batches(self):
        with self.sessions() as session:
            ids = list(session.scalars(select(Batch.id).order_by(Batch.created_at.desc()).limit(50)))
        return [self.get_batch(batch_id) for batch_id in ids]

    def control_batch(self, batch_id, action):
        batch = self.get_batch(batch_id)
        for item in batch["items"]:
            sources = {"pause":{"queued","preparing","render_queued","synthesizing","rendering","validating"},
                       "resume":{"paused","failed"},"cancel":{"queued","preparing","render_queued","synthesizing","rendering","validating","paused","failed","awaiting_renderer"}}[action]
            if item.status in sources:
                try: self.control(item.id, action)
                except QueueError as error:
                    if error.status_code != 409: raise
        return self.get_batch(batch_id)

    def request_generation(self, job_id, auto_render=False):
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if not job:
                raise QueueError("Trabalho não encontrado.", 404)
            if not job.manifest_path or job.status not in {"awaiting_renderer", "paused", "failed", "completed"}:
                raise QueueError("Prepare o projeto ou pause o trabalho antes de solicitar novos roteiros.")
            job.task, job.render_token = "generate", new_id()
            job.generation_options = {"auto_render":auto_render}
            job.error, job.progress = None, 0
            record(session, job, "queued", "Geração de roteiros PT/EN adicionada à fila local.")
        return self.get(job_id)

    def generate(self, job_id):
        from services.render_supervisor import run_job_process
        import shutil
        from services.media_tools import voice_model
        with self.sessions() as session:
            job = session.get(Job, job_id)
            token, story_id = job.render_token, job.story_id
            topic = session.get(Story, story_id).topic
            options = job.generation_options or {}
        workspace = None
        try:
            def checkpoint():
                with self.sessions() as session:
                    current = session.get(Job, job_id)
                    if self.interrupt_event.is_set() or current.render_token != token or current.status != "preparing":
                        raise Interrupted("Geração interrompida pelo controle da fila.")
            def update(payload):
                with self.sessions.begin() as session:
                    current = session.get(Job, job_id)
                    if current.render_token == token and current.status == "preparing":
                        current.progress, current.message, current.updated_at = payload["progress"], payload["message"], now()
            payload = {"mode":"scripts","topic":topic,"auto_topic":options.get("auto_topic",False),"seed_topic":options.get("seed_topic",""),"history":self.topic_history(),
                       "data_dir":str(self.data_dir),"ollama_url":self.config.ollama_url,"ollama_model":self.config.ollama_model,
                       "voices":{lang:str(voice_model(self.config,lang)) for lang in ("PT","EN")}}
            workspace, result = run_job_process(self.config, job_id, token, payload, self.get_settings(), checkpoint, update, "services.generate_job")
            checkpoint()
            scripts = {lang:ScriptInput.model_validate(data) for lang,data in result["scripts"].items()}
            with self.sessions.begin() as session:
                current = session.get(Job, job_id)
                if current.render_token != token or current.status != "preparing":
                    raise Interrupted("Geração interrompida antes de salvar.")
                if options.get("auto_topic"):
                    story = session.get(Story, story_id)
                    story.topic, story.topic_key = result["topic"], topic_key(result["topic"])
                for language, script in scripts.items():
                    saved = session.scalar(select(Script).where(Script.story_id == story_id, Script.language == language))
                    if saved is None:
                        saved = Script(story_id=story_id, language=language, content=script.model_dump())
                        session.add(saved)
                        session.flush()
                    else:
                        session.execute(delete(Scene).where(Scene.script_id == saved.id))
                        saved.content = script.model_dump()
                    for index, scene in enumerate(script.scenes):
                        session.add(Scene(script_id=saved.id, position=index, content=scene.model_dump()))
                (self.data_dir/"output"/story_id/"generation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                current.progress, current.error = 0, None
                if options.get("auto_render"):
                    current.task, current.render_token, current.render_languages = "render", new_id(), ["PT","EN"]
                    session.execute(delete(Video).where(Video.story_id == story_id))
                    record(session, current, "render_queued", "Roteiros PT/EN gerados e falas medidas; aguardando vídeos.")
                else:
                    record(session, current, "awaiting_renderer", "Roteiros PT/EN gerados localmente e ajustados. Revise ou solicite os vídeos.")
        except Interrupted:
            logger.info("Geração interrompida: %s", job_id)
        except Exception as error:
            logger.exception("Falha na geração: %s", job_id)
            with self.sessions.begin() as session:
                current = session.get(Job, job_id)
                if current.render_token == token and current.status == "preparing":
                    current.error = str(error)[:600] if isinstance(error, MediaError) else "Falha na geração. Consulte o log local."
                    record(session, current, "failed", current.error)
        finally:
            if workspace and workspace.exists() and workspace.resolve().is_relative_to((self.data_dir/"temp").resolve()):
                shutil.rmtree(workspace)

    def request_topics(self, count, seed_topic=""):
        with self.sessions.begin() as session:
            request = AIRequest(payload={"count":count,"seed_topic":seed_topic})
            session.add(request)
            session.flush()
            request_id = request.id
        return self.get_topics(request_id)

    def get_topics(self, request_id):
        with self.sessions() as session:
            request = session.get(AIRequest, request_id)
            if not request:
                raise QueueError("Solicitação de temas não encontrada.", 404)
            return {key:getattr(request,key) for key in ("id","status","progress","payload","result","error","created_at")}

    def cancel_topics(self, request_id):
        with self.sessions.begin() as session:
            request = session.get(AIRequest, request_id)
            if not request:
                raise QueueError("Solicitação de temas não encontrada.",404)
            if request.status not in {"queued","running"}:
                raise QueueError("A solicitação de temas já finalizou.")
            request.status = "cancelled"
        return self.get_topics(request_id)

    def claim_topics(self):
        with self.sessions.begin() as session:
            request = session.scalar(select(AIRequest).where(AIRequest.status == "queued").order_by(AIRequest.created_at).limit(1))
            if request:
                request.status = "running"
                return request.id

    def generate_topics(self, request_id):
        from services.render_supervisor import run_job_process
        import shutil
        workspace = None
        try:
            with self.sessions() as session:
                payload = dict(session.get(AIRequest, request_id).payload)
            def checkpoint():
                if self.interrupt_event.is_set() or self.get_topics(request_id)["status"] != "running":
                    raise Interrupted("Solicitação de ideias interrompida.")
            def update(progress):
                with self.sessions.begin() as session:
                    current = session.get(AIRequest, request_id)
                    if current.status == "running": current.progress = progress["progress"]
            payload.update({"mode":"topics","history":self.topic_history(),"data_dir":str(self.data_dir),
                            "ollama_url":self.config.ollama_url,"ollama_model":self.config.ollama_model})
            workspace, result = run_job_process(self.config, request_id, new_id(), payload, self.get_settings(), checkpoint, update, "services.generate_job")
            checkpoint()
            with self.sessions.begin() as session:
                current = session.get(AIRequest, request_id)
                if current.status == "running":
                    current.status, current.progress, current.result = "completed", 100, result
        except Interrupted:
            with self.sessions.begin() as session:
                current = session.get(AIRequest, request_id)
                if current.status == "running": current.status = "queued"
        except Exception as error:
            with self.sessions.begin() as session:
                current = session.get(AIRequest, request_id)
                current.status, current.error = "failed", str(error)[:600]
        finally:
            if workspace and workspace.exists() and workspace.resolve().is_relative_to((self.data_dir/"temp").resolve()):
                shutil.rmtree(workspace)


class Worker:
    def __init__(self, queue: QueueService):
        self.queue = queue
        self.stop_event = threading.Event()
        self.queue.interrupt_event = self.stop_event
        self.thread = threading.Thread(target=self.run, name="autovideo-worker", daemon=True)
        self.last_error: str | None = None

    def start(self):
        self.queue.recover()
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                topic_request = self.queue.claim_topics()
                if topic_request:
                    self.queue.generate_topics(topic_request)
                job_id = self.queue.claim()
                if job_id:
                    task = self.queue.get(job_id).task
                    if task == "render":
                        self.queue.render(job_id)
                    elif task == "generate":
                        self.queue.generate(job_id)
                    else:
                        self.queue.prepare(job_id)
                self.last_error = None
                interval = self.queue.get_settings().worker_poll_seconds
            except Exception:
                logger.exception("Falha no ciclo do worker")
                self.last_error = "Falha ao acessar a fila. Consulte o log local."
                interval = 2
            self.stop_event.wait(interval)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise RuntimeError("O worker não encerrou no prazo; a trava foi mantida.")
