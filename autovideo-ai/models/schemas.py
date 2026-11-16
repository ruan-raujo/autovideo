from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VIDEO_SPEC = {
    "duration_seconds": 80, "fps": 30, "frames": 2400,
    "width": 1080, "height": 1920, "container": "mp4",
    "video_codec": "h264", "audio_codec": "aac", "languages": ["PT", "EN"],
}


class CreateStory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=5, max_length=300)
    automatic: bool = False

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 5 or not re.search(r"[^\W\d_]", value, flags=re.UNICODE):
            raise ValueError("Informe um tema com pelo menos 5 caracteres e alguma letra.")
        if any(ord(character) < 32 for character in value):
            raise ValueError("O tema contém caracteres de controle.")
        return value


class QueueSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_poll_seconds: float = Field(default=1.0, ge=0.2, le=10)
    max_concurrent_jobs: Literal[1] = 1
    cpu_threads: int = Field(default=2, ge=1, le=4)
    render_memory_mb: int = Field(default=1600, ge=768, le=4096)
    subtitle_font_size: int = Field(default=62, ge=42, le=82)
    music_enabled: bool = False
    sfx_enabled: bool = False
    encoder: Literal["auto", "cpu", "nvenc"] = "auto"


class EventResponse(BaseModel):
    status: str
    message: str
    created_at: str


class JobResponse(BaseModel):
    id: str
    story_id: str
    topic: str
    status: str
    progress: int
    message: str
    error: str | None
    attempts: int
    created_at: str
    updated_at: str
    preparation_complete: bool
    video_available: bool = False
    script_available: bool = False
    script_languages: list[str] = Field(default_factory=list)
    video_languages: list[str] = Field(default_factory=list)
    task: str = "prepare"
    batch_id: str | None = None
    events: list[EventResponse] = Field(default_factory=list)


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
    counts: dict[str, int]


class CameraSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zoom_start: float = Field(default=1.0, ge=1.0, le=1.18)
    zoom_end: float = Field(default=1.06, ge=1.0, le=1.18)
    pan_x: float = Field(default=0.02, ge=-0.08, le=0.08)
    pan_y: float = Field(default=0.0, ge=-0.08, le=0.08)


class ElementSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str = Field(pattern=r"^(earth|mars|sun|moon|person|tree|building|snowflake|rocket|vent|microbe|asset_[0-9a-f]{32})$")
    x: float = Field(default=0.5, ge=-0.2, le=1.2)
    y: float = Field(default=0.5, ge=-0.2, le=1.2)
    scale: float = Field(default=1.0, ge=0.15, le=2.0)
    motion: Literal["none", "bob", "drift", "orbit", "spin", "walk"] = "bob"
    amplitude: float = Field(default=0.025, ge=0.0, le=0.2)
    speed: float = Field(default=1.0, ge=0.1, le=3.0)
    expression: Literal["neutral", "happy", "worried"] = "neutral"
    opacity_start: float = Field(default=1.0,ge=0,le=1)
    opacity_end: float = Field(default=1.0,ge=0,le=1)


class SceneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frames: int = Field(ge=30, le=900)
    title: str = Field(min_length=1, max_length=70)
    narration: str = Field(min_length=5, max_length=550)
    background: Literal["space", "city", "ocean", "snow", "dusk", "studio"] = "space"
    elements: list[ElementSpec] = Field(default_factory=list, max_length=12)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    transition: Literal["crossfade", "cut", "wipe", "slide"] = "crossfade"
    transition_frames: int = Field(default=10, ge=0, le=30)

    @field_validator("narration", "title")
    @classmethod
    def safe_text(cls, text):
        if any(char in text for char in ("\x00", "{", "}", "\\", "[[", "]]")):
            raise ValueError("Use texto simples, sem comandos de voz ou formatação.")
        cleaned = " ".join(text.split())
        if not cleaned:
            raise ValueError("Informe um texto; espaços em branco não são suficientes.")
        return cleaned


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["PT", "EN"] = "PT"
    scenes: list[SceneInput] = Field(min_length=5, max_length=20)

    @model_validator(mode="after")
    def exact_timeline(self):
        if sum(scene.frames for scene in self.scenes) != 2400:
            raise ValueError("A soma das cenas deve ser 2400 quadros: exatamente 80 segundos a 30 fps.")
        words = sum(len(scene.narration.split()) for scene in self.scenes)
        if not 100 <= words <= 240:
            raise ValueError(f"Use entre 100 e 240 palavras; recebido: {words}. O encaixe natural será verificado pela voz local.")
        return self


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    languages: list[Literal["PT", "EN"]] = Field(default_factory=lambda: ["PT", "EN"], min_length=1, max_length=2)

    @field_validator("languages")
    @classmethod
    def unique_languages(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Não repita idiomas.")
        return values


class GenerateScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_render: bool = False


class GenerateTopicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(default=5, ge=1, le=20)
    seed_topic: str = Field(default="", max_length=300)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(default=1, ge=1, le=20)
    automatic: bool = True
    topic: str = Field(default="", max_length=300)
    topics: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def valid_topics(self):
        if self.topics is not None:
            if len(self.topics) != self.count:
                raise ValueError("A quantidade de temas deve corresponder à quantidade de histórias.")
            self.topics = [CreateStory(topic=value).topic for value in self.topics]
        elif not self.automatic:
            if self.count == 1 and self.topic:
                self.topics = [CreateStory(topic=self.topic).topic]
            else:
                raise ValueError("Informe a lista de temas ou ative a geração automática.")
        return self


class AssetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    license: str = Field(min_length=3, max_length=200)

    @field_validator("name","license",mode="before")
    @classmethod
    def clean_metadata(cls,value):
        return value.strip() if isinstance(value,str) else value


class AssetUpload(AssetMetadata):
    image_base64: str = Field(min_length=12, max_length=2_800_000)
