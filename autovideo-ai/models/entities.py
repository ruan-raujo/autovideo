from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Story(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic: Mapped[str]
    topic_key: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[str] = mapped_column(default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100"),
        CheckConstraint("status IN ('queued','preparing','awaiting_renderer','paused','cancelled','failed','render_queued','synthesizing','rendering','validating','completed')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), unique=True)
    status: Mapped[str] = mapped_column(default="queued", index=True)
    progress: Mapped[int] = mapped_column(default=0)
    message: Mapped[str] = mapped_column(default="Aguardando preparação local.")
    error: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)
    manifest_path: Mapped[str | None]
    task: Mapped[str] = mapped_column(default="prepare", server_default="prepare")
    render_token: Mapped[str | None]
    render_languages: Mapped[list] = mapped_column(JSON, default=lambda: ["PT"], server_default='["PT"]')
    generation_options: Mapped[dict | None] = mapped_column(JSON)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[str] = mapped_column(default=now, index=True)
    updated_at: Mapped[str] = mapped_column(default=now)


class Script(Base):
    __tablename__ = "scripts"
    __table_args__ = (UniqueConstraint("story_id", "language"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"))
    language: Mapped[str]
    content: Mapped[dict] = mapped_column(JSON)


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("script_id", "position"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id"))
    position: Mapped[int]
    content: Mapped[dict] = mapped_column(JSON)


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("story_id", "language"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"))
    language: Mapped[str]
    file_path: Mapped[str]
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class VisualAsset(Base):
    __tablename__ = "visual_assets"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str]
    file_path: Mapped[str]
    license: Mapped[str]
    kind: Mapped[str]


class GenerationEvent(Base):
    __tablename__ = "generation_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str]
    message: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)


class AIRequest(Base):
    __tablename__ = "ai_requests"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None]
    progress: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    requested_count: Mapped[int]
    automatic: Mapped[bool]
    created_at: Mapped[str] = mapped_column(default=now)
