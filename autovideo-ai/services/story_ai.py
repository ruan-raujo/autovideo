"""Structured local ideas, bilingual narration and measured timing repair."""
from copy import deepcopy
import json
import re
import unicodedata

from pydantic import BaseModel, Field

from models.schemas import ScriptInput
from services.media_tools import MediaError

FRAMES = [150, 210, 240, 270, 270, 270, 240, 300, 300, 150]
BACKGROUNDS = ["space", "city", "ocean", "snow", "dusk", "studio"]


def compose_visuals(scene,topic,index):
    """Map concrete narration concepts to the owned visual vocabulary."""
    text=(scene["narration"]+" "+scene["title"]).casefold()
    topic=topic.casefold()
    elements=[]
    def add(asset,x,y,scale=1,motion="bob",**options):
        elements.append(dict(asset=asset,x=x,y=y,scale=scale,motion=motion,**options))
    if any(word in text for word in ("micrób","microb","hidroterm","hydrothermal")):
        scene["background"]="ocean"
        add("vent",.35,.63,1.3,"none"); add("microbe",.72,.47,.65,"orbit")
    elif any(word in text for word in ("neve","gelo","frio","congel","snow","freez","cold","ice")):
        scene["background"]="snow"
        add("building",.28,.59,1.1,"none"); add("person",.65,.58,1.0,"walk",expression="worried")
        add("snowflake",.76,.32,.5,"drift")
    elif index<3 or any(word in text for word in ("órbita","orbita","gravidade","rotação","orbit","gravity","rotation")):
        scene["background"]="space"
        add("mars" if "marte" in topic or "mars" in topic else "earth",.43,.56,1.4,"spin",speed=.2)
        if "sol" in topic or "sun" in topic:
            if index==0: add("sun",.76,.32,.55,"none",opacity_end=0)
        elif "lua" in topic or "moon" in topic:
            add("moon",.78,.33,.5,"orbit",opacity_end=0 if index==0 else 1)
    elif any(word in text for word in ("plant","árvore","florest","forest","tree")):
        scene["background"]="dusk"
        add("tree",.3,.57,1.1); add("person",.68,.59,1,"walk")
    if elements:
        scene["elements"]=elements
    scene["transition"]="wipe" if index>0 and index%3==0 else "crossfade"
    scene["transition_frames"]=10
    return scene


def normalized_topic(text):
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    for filler in ("de forma instantanea", "de forma abrupta", "de repente", "instantaneamente", "abruptamente", "agora"):
        value = value.replace(filler, "")
    return "".join(char for char in value if char.isalnum())


def generate_topics(client, count, history, checkpoint=lambda:None, seed_topic=""):
    excluded = [text[:180] for text in history[-60:]]
    schema = {"type":"object", "properties":{"topics":{"type":"array","items":{"type":"string","minLength":12,"maxLength":160},"minItems":count,"maxItems":count}},"required":["topics"],"additionalProperties":False}
    seen = {normalized_topic(text) for text in history}
    ideas = []
    for attempt in range(4):
        checkpoint()
        proposal_count=min(20,max(3,count-len(ideas)))
        prompt = (
            f"Crie {proposal_count} temas originais em português brasileiro para vídeos científicos hipotéticos. "
            "Cada tema deve ser uma pergunta curta e específica começando com 'E se'. Varie astronomia, ecologia, tecnologia e história natural. "
            "A hipótese precisa alterar uma condição real de maneira clara: por exemplo desaparecer o Sol, parar a rotação terrestre ou perder a Lua. "
            "Rejeite propriedades que já existem, jogos de palavras e condições vagas como 'a Terra ter duas faces'. "
            "Não repita ou apenas reformule a mesma hipótese. Não afirme eventos imaginários como reais. "
            f"Evite estes temas já usados: {json.dumps(excluded+ideas,ensure_ascii=False)}. Responda JSON com topics."
        )
        prompt+=f" Nesta tentativa, varie especialmente na área de {['astronomia','ecologia','tecnologia','planeta Terra'][attempt]}. Evite acrescentar números arbitrários à hipótese."
        if seed_topic:
            prompt += " Use este assunto como inspiração, criando hipóteses diferentes: "+json.dumps(seed_topic,ensure_ascii=False)
        schema["properties"]["topics"].update(minItems=proposal_count, maxItems=proposal_count)
        try:
            data = client.generate(prompt, schema, checkpoint, temperature=.7)
        except MediaError:
            continue
        candidates = []
        for candidate in data.get("topics", []):
            if isinstance(candidate,str):
                candidate = " ".join(candidate.split()).split("?",1)[0].split(",",1)[0].strip()+"?"
                if candidate.lower().startswith("e se "):
                    candidates.append(candidate)
        if not candidates:
            print("Topic response rejected:",json.dumps(data,ensure_ascii=False)[:600],flush=True)
            continue
        review_schema = {"type":"object","properties":{"evaluations":{"type":"array","minItems":len(candidates),"maxItems":len(candidates),"items":{"type":"object","properties":{"index":{"type":"integer","minimum":0,"maximum":max(0,len(candidates)-1)},"reason":{"type":"string","maxLength":160},"decision":{"type":"string","enum":["accept","reject_already_true","reject_unclear","reject_duplicate"]}},"required":["index","reason","decision"],"additionalProperties":False}}},"required":["evaluations"],"additionalProperties":False}
        review = client.generate("Review topics for a series of EXPLICIT THOUGHT EXPERIMENTS, not real events. Accept any clear, specific change to an existing condition. Impossible premises are allowed: the Sun disappearing, gravity changing, all pollinators vanishing. Do NOT reject because the change is impossible to cause, has serious effects, or resembles a gradual change already occurring. Reject only an EXACT condition already true, an unclear/empty premise or a duplicate of another topic. Explain briefly, then decide. Use zero-based indices. Topics: "+json.dumps(candidates,ensure_ascii=False), review_schema, checkpoint, temperature=.4)
        approved = {item["index"] for item in review.get("evaluations",[]) if item.get("decision")=="accept" or item.get("valid") is True}
        print("Topic review:",json.dumps({"candidates":candidates,"review":review},ensure_ascii=False)[:1500],flush=True)
        for index, topic in enumerate(candidates):
            if index not in approved:
                continue
            if not isinstance(topic, str):
                continue
            topic = " ".join(topic.split())
            key = normalized_topic(topic)
            if 5 <= len(topic) <= 300 and key and key not in seen:
                seen.add(key)
                ideas.append(topic)
        if len(ideas) >= count:
            return ideas[:count]
    raise MediaError("O modelo não produziu a quantidade solicitada de temas inéditos. Tente novamente.")


def draft_schema():
    return {"type":"object","properties":{"scenes":{"type":"array","minItems":10,"maxItems":10,"items":{
        "type":"object","properties":{"title":{"type":"string","maxLength":60},"narration":{"type":"string","minLength":35,"maxLength":150},"background":{"type":"string","enum":BACKGROUNDS}},
        "required":["title","narration","background"],"additionalProperties":False}}},"required":["scenes"],"additionalProperties":False}


def build_script(client, topic, language, source=None, checkpoint=lambda:None):
    from services.editorial import reference_context
    budgets = [int(frames/30*(2.1 if language == "PT" else 1.9)) for frames in FRAMES]
    guidance = (
        "You write careful, engaging narration for hypothetical science shorts. Clearly label impossible scenarios as thought experiments. "
        "Never invent scientific measurements, certainty, sources or quotes. Use short spoken sentences, no digits or abbreviations. "
        "Ten scenes: hook; two setup scenes; four consequence scenes; two surprising scenes; a memorable ending. "
        "Avoid filler, repeated questions and repetitive descriptions. Every scene advances the same story. "
        f"Language: {'Brazilian Portuguese' if language == 'PT' else 'US English'}. "
        f"Maximum word counts per scene, in order: {budgets}. Aim just below each maximum. "
        f"Minimum word counts per scene, in order: {[max(6,int(budget*.75)) for budget in budgets]}. "
        "Total narration MUST contain at least one hundred and fifteen words. Do not replace full narration with tiny summaries. "
        "Include title, narration and an appropriate background for every scene. Exactly ten scenes. "
        "Respect the word budgets; long narration cannot be cut. Return only the requested JSON. "
    )
    if source:
        content = {"scenes":[{"title":scene["title"],"narration":scene["narration"]} for scene in source["scenes"]]}
        guidance += "Translate/adapt this Portuguese story to concise English, preserving its meaning and scene order: "+json.dumps(content,ensure_ascii=False)
    else:
        guidance += "Topic: "+json.dumps(topic,ensure_ascii=False)
    lowered = topic.casefold()
    reference_notes,_=reference_context(topic)
    guidance+=" Reference constraints: "+json.dumps(reference_notes,ensure_ascii=False)
    if "sol" in lowered:
        guidance += " Scientific constraints: the Sun is only one star. Its disappearance would not remove other stars or all energy in the universe. Sunlight takes about eight minutes to reach Earth. Surface cooling is gradual, stored heat remains, and some microbes use chemical energy."
    if any(word in lowered for word in ("rotação","girar","girasse")):
        guidance += " Scientific constraints: gravity would remain if Earth stopped rotating. Inertia of air, oceans and objects matters. Do not claim everyone would float into space."
    if "dinossaur" in lowered:
        guidance += " Scientific constraints: modern birds are living dinosaurs. The hypothetical scenario concerns non-avian dinosaurs; different species lived in different geological periods."
    errors = ""
    for attempt in range(3):
        checkpoint()
        try:
            draft = client.generate(guidance+errors, draft_schema(), checkpoint, temperature=.3, _plain=attempt>0)
        except MediaError as error:
            errors = "\nPrevious output was incomplete. Keep every narration very short, under one hundred and fifty characters. Complete all ten scenes."
            continue
        try:
            if len(draft.get("scenes",[])) != 10:
                raise ValueError("Exactly ten scenes are required.")
            narrations = [normalized_topic(item.get("narration","")) for item in draft["scenes"]]
            if len(set(narrations)) != len(narrations):
                raise ValueError("Scenes must not repeat the same narration.")
            scenes = []
            for index, item in enumerate(draft["scenes"]):
                words = len(item["narration"].split())
                if words < 4:
                    raise ValueError(f"Scene {index+1} needs complete narration.")
                scene = dict(item, frames=FRAMES[index], elements=[])
                if not source:
                    scene=compose_visuals(scene,topic,index)
                if source:
                    for key in ("background", "elements", "camera", "transition", "transition_frames"):
                        if key in source["scenes"][index]: scene[key] = source["scenes"][index][key]
                scenes.append(scene)
            return ScriptInput.model_validate({"language":language,"scenes":scenes}).model_dump()
        except (ValueError, KeyError, TypeError) as error:
            print(f"Draft {language} attempt {attempt+1} rejected: {str(error)[:180]}",flush=True)
            errors = "\nPrevious draft failed validation. Rewrite the whole JSON. Error: "+str(error)[:500]
    # Small models may loop inside a large constrained array. Generate bounded
    # scenes independently, retaining context and applying all final validators.
    print(f"Draft {language}: using individual scene recovery",flush=True)
    scenes=[]
    roles=["opening question","introduce the assumption","explain the immediate change","first consequence","second consequence","develop the stakes","a different consequence","surprising insight","explain that insight","memorable conclusion"]
    single_schema=draft_schema()["properties"]["scenes"]["items"]
    for index, role in enumerate(roles):
        context={"topic":topic,"scene":index+1,"role":role,"previous":[s["narration"] for s in scenes]}
        if source:
            context["translate_this_scene"]=source["scenes"][index]["narration"]
        prompt=(f"Write ONLY scene {index+1} of a ten-scene hypothetical science short in {'Brazilian Portuguese' if language=='PT' else 'English'}. "
                f"Use between {max(7,budgets[index]-5)} and {budgets[index]} spoken words. Short title and one complete narration. "
                "No digits. Advance the story; do not repeat previous narration. Preserve scientific uncertainty. "
                "Return JSON containing title, narration, background. Context: "+json.dumps(context,ensure_ascii=False))
        for retry in range(3):
            checkpoint()
            item=client.generate(prompt,single_schema,checkpoint,temperature=.4,_plain=True)
            try:
                from models.schemas import SceneInput
                scene=SceneInput.model_validate(dict(item,frames=FRAMES[index],elements=[])).model_dump()
                if not source:
                    scene=compose_visuals(scene,topic,index)
                if normalized_topic(scene["narration"]) in {normalized_topic(s["narration"]) for s in scenes}:
                    raise ValueError("Repeated narration")
                if source:
                    for key in ("background","elements","camera","transition","transition_frames"):
                        if key in source["scenes"][index]: scene[key]=source["scenes"][index][key]
                scenes.append(scene)
                break
            except (ValueError,KeyError,TypeError) as error:
                print(f"Single scene {language} {index+1} retry {retry+1}: {str(error)[:600]} | {json.dumps(item,ensure_ascii=False)[:500]}",flush=True)
                prompt+=" Rewrite this scene; previous validation error: "+str(error)[:200]
        else:
            raise MediaError(f"O modelo repetiu ou invalidou a cena {index+1}; tente gerar o roteiro novamente.")
    try:
        return ScriptInput.model_validate({"language":language,"scenes":scenes}).model_dump()
    except ValueError as error:
        raise MediaError("O roteiro recuperado não passou na validação: "+str(error)[:300]) from error


def repair_and_measure(client, script, voice_path, threads, checkpoint=lambda:None):
    from services.narration import load_voice, synthesize_scene
    script = deepcopy(script)
    originals = deepcopy(script)
    reports = []
    last_failures = []
    for attempt in range(6):
        client.unload()
        checkpoint()
        voice = load_voice(voice_path, threads)
        failures = []
        reports = []
        for index, scene in enumerate(script["scenes"]):
            checkpoint()
            try:
                _, _, tempo, raw = synthesize_scene(voice, scene["narration"], scene["frames"]/30, index+1)
                reports.append({"scene":index+1,"seconds":raw,"tempo":tempo})
            except MediaError as error:
                failures.append((index, str(error)))
        del voice
        if not failures:
            return ScriptInput.model_validate(script).model_dump(), reports
        last_failures = failures
        print(f"Timing {script['language']} attempt {attempt+1}: "+json.dumps(failures,ensure_ascii=False),flush=True)
        for index, error in failures:
            scene = script["scenes"][index]
            count = len(scene["narration"].split())
            target = max(7, min(int(count*.65),int(scene["frames"]/30*1.8))) if "longa" in error or "não cabe" in error or "excedeu" in error else max(8,count+5,int(scene["frames"]/30*1.5))
            if "alinhar" in error: target = count
            max_chars = min(180,max(45,target*6+5))
            action = "Expand the idea with one meaningful sentence; do not shorten it." if "curta" in error else "Shorten it to its central meaning."
            prompt = (f"Write a NEW version in {'Brazilian Portuguese' if script['language']=='PT' else 'English'}, approximately {target} words, at most {max_chars} characters. "
                      f"{action} Use one or two complete, simple spoken sentences. "
                      "No introduction or explanation. Spell out numbers. Original idea: "+json.dumps(originals["scenes"][index]["narration"],ensure_ascii=False))
            schema = {"type":"object","properties":{"text":{"type":"string","minLength":20,"maxLength":max_chars}},"required":["text"],"additionalProperties":False}
            data = client.generate(prompt, schema, checkpoint)
            print(f"Rewritten {script['language']} scene {index+1}: {count} -> {len(data['text'].split())} words",flush=True)
            scene["narration"] = data["text"]
    raise MediaError("A IA não conseguiu ajustar a narração sem cortes. Últimos erros: "+str(last_failures)[:450])
