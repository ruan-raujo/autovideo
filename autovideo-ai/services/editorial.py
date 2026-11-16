"""Local editorial consistency checks, with a small explicit reference library."""
from copy import deepcopy
import json
import re

from models.schemas import SceneInput, ScriptInput
from services.media_tools import MediaError


def reference_context(topic):
    text=topic.casefold()
    notes=[]; sources=[]
    if "marte" in text or "mars" in text or "gravidade" in text:
        notes += ["Weight depends on gravitational acceleration; changing gravity does not itself change an object's mass or inertia. Lower gravity does not mean no gravity or objects floating without support.",
                  "For the same initial upward speed, weaker downward acceleration gives a higher jump and longer flight, ignoring drag. Do not invent collapsing buildings, failing legs, spontaneous wind or inward-falling moons."]
        sources += ["https://www.grc.nasa.gov/WWW/K-12/Enginesim/weight_and_mass.htm","https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/free-fall-without-air-resistance/"]
    if "marte" in text or "mars" in text:
        notes += ["Mars has a thin, mostly carbon dioxide atmosphere and no present-day surface rivers of liquid water. Any human base is hypothetical. A gravity change alone does not create rivers or breathable air. Keep the stated half-gravity and one-month premise, spelling numbers out."]
        sources += ["https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/mars/"]
    if "poliniz" in text or "pollinat" in text:
        notes += ["Insect pollination supports reproduction of many plants, but not all plants or all food production depend on it. Wind, self-pollination and vertebrate pollinators also exist.",
                  "If ALL pollinating insects disappear irreversibly, a surviving bee cannot appear later. The premise does not stop wind or instantly remove flower color, warmth, oxygen or all life. Effects on fruits, seeds and food webs occur over reproductive cycles. Avoid absolute claims that all fruits vanish."]
        sources += ["https://www.fao.org/agriculture/crops/core-themes/theme/biodiversity/pollination/en/","https://www.fao.org/4/i3157e/i3157e.pdf"]
    if "sol" in text or "sun" in text:
        notes += ["Earth receives sunlight after about eight minutes. Cooling is gradual, not instant freezing. Other stars, stored heat and some chemically powered ecosystems remain. The premise is an impossible thought experiment, not a forecast."]
        sources += ["https://science.nasa.gov/sun/facts/"]
    return notes,sources


def obvious_contradictions(topic,script):
    issues=[]
    pollinating="poliniz" in topic.casefold() or "pollinat" in topic.casefold()
    for index,scene in enumerate(script["scenes"]):
        text=scene["narration"].casefold()
        if pollinating and re.search(r"abelha ainda (voa|vive)|bee still (flies|lives)|one bee.*flies",text):
            issues.append({"scene":index+1,"reason":"A surviving bee contradicts the disappearance of every pollinating insect."})
    return issues


def review_script(client,topic,script,source=None,checkpoint=lambda:None):
    script=deepcopy(script)
    notes,sources=reference_context(topic)
    item={"type":"object","properties":{"scene":{"type":"integer","minimum":1,"maximum":len(script["scenes"])},"reason":{"type":"string","maxLength":180},"replacement":{"type":"string","minLength":20,"maxLength":180}},"required":["scene","reason","replacement"],"additionalProperties":False}
    schema={"type":"object","properties":{"issues":{"type":"array","maxItems":len(script["scenes"]),"items":item}},"required":["issues"],"additionalProperties":False}
    revisions=[]
    for attempt in range(3):
        checkpoint()
        payload={"topic":topic,"language":script["language"],"reference_notes":notes,
                 "scenes":[{"scene":i+1,"seconds":s["frames"]/30,"narration":s["narration"]} for i,s in enumerate(script["scenes"])],
                 "known_contradictions":obvious_contradictions(topic,script)}
        if source:
            payload["Portuguese_meaning_to_preserve"]=[s["narration"] for s in source["scenes"]]
        prompt=("Review this hypothetical science narration for actual contradictions, unsupported claims and preservation of its exact premise. "
                "Scene one must introduce the central hypothetical change, rather than merely stating an existing fact. "
                "The premise may be impossible; do not reject it for that. Distinguish known principles from speculative consequences. "
                "Use the reference notes as constraints. Do not demand stylistic rewrites or flag a sentence for correctly denying a false claim. "
                "For each real issue, provide one NEW complete replacement narration in the requested language, about two spoken words per second of its slot, at most eighteen words. "
                "Spell out numbers. Preserve the premise and all unaffected scenes. Return issues:[] if sound. Data: "+json.dumps(payload,ensure_ascii=False))
        result=client.generate(prompt,schema,checkpoint,temperature=.6,_plain=True)
        issues=result.get("issues")
        if not isinstance(issues,list):
            raise MediaError("A revisão editorial retornou uma resposta inválida.")
        if not issues and not obvious_contradictions(topic,script):
            return ScriptInput.model_validate(script).model_dump(),{"passes":attempt+1,"revisions":revisions,"reference_sources":sources,"human_review_recommended":True}
        if not issues:
            continue
        for issue in issues:
            index=issue.get("scene",0)-1
            if not 0<=index<len(script["scenes"]) or not isinstance(issue.get("replacement"),str):
                raise MediaError("A revisão editorial indicou uma cena inválida.")
            replacement=SceneInput.model_validate(dict(script["scenes"][index],narration=issue["replacement"]))
            script["scenes"][index]=replacement.model_dump()
            revisions.append({"scene":index+1,"reason":issue.get("reason","")})
        print(f"Editorial {script['language']} pass {attempt+1}: "+json.dumps(issues,ensure_ascii=False)[:1800],flush=True)
    raise MediaError("A revisão editorial ainda encontrou contradições. Revise o roteiro ou solicite nova geração.")
