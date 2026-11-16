from copy import deepcopy

from services.media_tools import MediaError
from services.story_ai import build_script, compose_visuals
from tests.test_stage2 import example_script


def test_incomplete_model_json_is_retried_and_validated():
    class Client:
        calls = 0
        def generate(self, prompt, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise MediaError("Incomplete JSON")
            return {"scenes":[{key:scene[key] for key in ("title","narration","background")} for scene in example_script()["scenes"]]}
    client = Client()
    script = build_script(client,"E se o Sol desaparecesse?","PT")
    assert client.calls == 2 and script["language"] == "PT"
    assert sum(scene["frames"] for scene in script["scenes"]) == 2400


def test_repetitive_drafts_recover_one_scene_at_a_time():
    original=example_script()["scenes"]
    class Client:
        calls=0
        def generate(self,prompt,*args,**kwargs):
            self.calls+=1
            if self.calls<=3:
                return {"scenes":[{key:original[0][key] for key in ("title","narration","background")}] * 10}
            scene=original[self.calls-4]
            return {key:scene[key] for key in ("title","narration","background")}
    client=Client()
    script=build_script(client,"E se o Sol desaparecesse?","PT")
    assert client.calls==13 and len(script["scenes"])==10
    assert len({scene["narration"] for scene in script["scenes"]})==10


def test_concrete_visuals_follow_story_and_disappearance():
    scene=compose_visuals({"title":"O Sol","narration":"Imagine o Sol desaparecendo.","background":"city"},"E se o Sol desaparecesse?",0)
    assert scene["background"]=="space"
    sun=next(element for element in scene["elements"] if element["asset"]=="sun")
    assert sun["opacity_end"]==0
    scene=compose_visuals({"title":"Vida no fundo","narration":"Micróbios usam fontes hidrotermais.","background":"space"},"E se o Sol desaparecesse?",8)
    assert {element["asset"] for element in scene["elements"]}=={"microbe","vent"}
    mars=compose_visuals({"title":"Gravidade","narration":"Imagine uma mudança em Marte.","background":"space"},"E se a gravidade de Marte mudasse?",0)
    assert mars["elements"][0]["asset"]=="mars"
