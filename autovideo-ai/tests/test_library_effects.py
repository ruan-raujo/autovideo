import base64
from io import BytesIO

import numpy as np
from PIL import Image, ImageChops

from animation.renderer import SceneRenderer, person_pose, transition_frame
from models.schemas import SceneInput
from services.audio_effects import mix_effects
from services.encoding import select_encoder


def image_payload():
    stream=BytesIO()
    Image.new("RGBA",(20,10),(255,0,0,180)).save(stream,"PNG")
    return {"name":"Meu objeto","license":"Autoria própria","image_base64":base64.b64encode(stream.getvalue()).decode()}


def test_library_crud_and_rejected_files(client):
    from services.assets import BUILTINS
    assert len(client.get("/api/assets").json()["items"])==len(BUILTINS)
    assert client.delete("/api/assets/earth").status_code==409
    response=client.post("/api/assets",json=image_payload())
    assert response.status_code==201,response.text
    asset=response.json()
    image=client.get(asset["image_url"])
    assert image.status_code==200 and image.headers["content-type"]=="image/png"
    assert client.put(f"/api/assets/{asset['id']}",json={"name":"Novo nome","license":"CC0"}).status_code==200
    payload=image_payload(); payload["image_base64"]=base64.b64encode(b"<svg>not a raster image</svg>").decode()
    assert client.post("/api/assets",json=payload).status_code==422
    assert client.delete(f"/api/assets/{asset['id']}").status_code==200
    assert client.get(asset["image_url"]).status_code==404


def test_joint_animation_and_transition_endpoints():
    first=person_pose("neutral",0,False,False)
    other=person_pose("neutral",2,True,False)
    assert ImageChops.difference(first,other).convert("RGB").getbbox()
    previous=Image.new("RGB",(80,120),"red")
    current=Image.new("RGB",(80,120),"blue")
    for kind in ("crossfade","wipe","slide"):
        midway=transition_frame(previous,current,kind,3,10)
        assert midway.tobytes()!=current.tobytes() and midway.tobytes()!=previous.tobytes()
        assert transition_frame(previous,current,kind,9,10).tobytes()==current.tobytes()


def test_asset_referenced_by_saved_script_cannot_be_deleted(client,app):
    from tests.test_stage2 import prepared, example_script
    asset=client.post("/api/assets",json=image_payload()).json()
    job=prepared(client,app)
    script=example_script()
    script["scenes"][0]["elements"]=[{"asset":asset["id"]}]
    assert client.put(f"/api/videos/{job['id']}/script",json=script).status_code==200
    assert client.delete(f"/api/assets/{asset['id']}").status_code==409
    assert client.get(asset["image_url"]).status_code==200


def test_custom_image_renders_without_filesystem_escape(client,app,tmp_path):
    asset=client.post("/api/assets",json=image_payload()).json()
    scene=SceneInput(frames=90,title="Objeto",narration="Um objeto na cena.",elements=[{"asset":asset["id"]}])
    renderer=SceneRenderer(scene,0,1,asset_folder=app.state.assets.folder)
    assert renderer.frame(20).size==(1080,1920)
    renderer.export_svg(tmp_path/"scene.svg")
    assert "data:image/png;base64" in (tmp_path/"scene.svg").read_text()


def test_effects_preserve_timeline_and_prevent_clipping():
    source=np.full(8000,32760,dtype=np.int16)
    result=mix_effects(source,1000,[60,60,60,60],True,True)
    assert result.dtype==np.int16 and len(result)==len(source)
    assert result.min()>30000 and result.max()<=32767
    silent=mix_effects(np.zeros(8000,dtype=np.int16),1000,[60]*4,True,True)
    assert np.max(np.abs(silent))>100
    assert mix_effects(source,1000,[60]*4) is source


def test_encoder_auto_falls_back_when_executable_missing():
    assert select_encoder("a-nonexistent-ffmpeg", "auto")=="libx264"


def test_opacity_animation_reveals_object_without_changing_frame_size():
    scene=SceneInput(frames=60,title="Luz",narration="A luz muda durante esta cena.",
                     camera={"zoom_start":1,"zoom_end":1,"pan_x":0,"pan_y":0},
                     elements=[{"asset":"sun","motion":"none","opacity_start":0,"opacity_end":1}])
    renderer=SceneRenderer(scene,0,1)
    first,last=renderer.frame(0),renderer.frame(59)
    assert first.size==last.size==(1080,1920)
    assert first.getpixel((540,960))!=last.getpixel((540,960))
