"""Measure all scenes before committing to a full render."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Config
from models.schemas import ScriptInput
from services.media_tools import voice_model
from services.narration import load_voice, synthesize_scene

if __name__ == "__main__":
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    script = ScriptInput.model_validate(data.get("script", data))
    voice = load_voice(voice_model(Config(), script.language), 1)
    failed = False
    for index, scene in enumerate(script.scenes, 1):
        try:
            _, words, tempo, duration = synthesize_scene(voice, scene.narration, scene.frames/30, index)
            print(index, round(duration, 2), round(tempo, 3), len(words), flush=True)
        except Exception as error:
            failed = True
            print(index, str(error), flush=True)
    sys.exit(1 if failed else 0)
