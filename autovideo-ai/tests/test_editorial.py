from copy import deepcopy
import pytest

from services.editorial import obvious_contradictions, review_script
from services.media_tools import MediaError
from tests.test_stage2 import example_script


def test_editorial_repairs_premise_contradiction_and_records_sources():
    topic="E se todos os insetos polinizadores desaparecessem?"
    script=deepcopy(example_script())
    script["scenes"][7]["narration"]="Num jardim isolado, uma abelha ainda voa apesar de tudo."
    assert obvious_contradictions(topic,script)
    class Client:
        calls=0
        def generate(self,*args,**kwargs):
            self.calls+=1
            return {"issues":[{"scene":8,"reason":"A bee contradicts the premise.","replacement":"Algumas plantas usam o vento para transportar pólen. Nem todas dependem de insetos para sua reprodução."}]} if self.calls==1 else {"issues":[]}
    revised,report=review_script(Client(),topic,script)
    assert not obvious_contradictions(topic,revised)
    assert report["passes"]==2 and report["reference_sources"] and report["revisions"][0]["scene"]==8


def test_editorial_rejects_invalid_scene_instead_of_publishing():
    class Client:
        def generate(self,*args,**kwargs):
            return {"issues":[{"scene":999,"replacement":"Texto que não pode ser aplicado a uma cena inexistente."}]}
    with pytest.raises(MediaError):
        review_script(Client(),"E se o Sol desaparecesse?",example_script())
