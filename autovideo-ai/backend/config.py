import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTOVIDEO_", env_file=ROOT / ".env", extra="ignore"
    )
    data_dir: Path = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "AutoVideoAI"
    worker_enabled: bool = True
    # Optional overrides; bundled local tools/voice are discovered automatically.
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    voice_path: Path | None = None
    voice_en_path: Path | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b-instruct-2507-q4_K_M"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "database" / "autovideo.sqlite3"

    def prepare_directories(self) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        for name in ("database", "output", "temp", "logs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
