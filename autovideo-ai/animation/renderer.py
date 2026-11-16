"""Data-driven SVG layers rasterized once, then transformed for every frame."""
from functools import lru_cache
from io import BytesIO
import base64
import math
from pathlib import Path
import random
import textwrap
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont
import resvg_py

from backend.config import ROOT
from models.schemas import ElementSpec

WIDTH, HEIGHT, FPS = 1080, 1920, 30
COLORS = {"space": "#14263e", "city": "#253d59", "ocean": "#164c66", "snow": "#9bbacb", "dusk": "#d9a17e", "studio": "#d7dace"}


def default_elements(background):
    if background == "space":
        values = [("earth", .43, .53, 1.45, "spin"), ("moon", .77, .32, .5, "orbit")]
    elif background == "ocean":
        values = [("earth", .5, .46, 1.25, "bob"), ("rocket", .75, .6, .4, "drift")]
    elif background == "snow":
        values = [("building", .3, .58, 1.3, "none"), ("person", .66, .59, 1.0, "walk"), ("snowflake", .75, .3, .45, "drift")]
    else:
        values = [("building", .25, .55, 1.2, "none"), ("tree", .75, .55, .85, "bob"), ("person", .52, .59, 1.05, "walk")]
    return [ElementSpec(asset=asset, x=x, y=y, scale=scale, motion=motion) for asset, x, y, scale, motion in values]


@lru_cache(maxsize=24)
def sprite(asset, expression="neutral"):
    source = (ROOT / "assets" / "svg" / f"{asset}.svg").read_text(encoding="utf-8")
    if asset == "person":
        if expression == "happy":
            source = source.replace('d="M234 175h44"', 'd="M234 170q22 27 44 0"')
        elif expression == "worried":
            source = source.replace('d="M234 175h44"', 'd="M234 183q22-27 44 0"')
    return Image.open(BytesIO(resvg_py.svg_to_bytes(svg_string=source))).convert("RGBA")


@lru_cache(maxsize=64)
def person_pose(expression, pose, speaking, blink):
    """Rasterize eight joint poses once; never run SVG rasterization per frame."""
    root = ET.parse(ROOT / "assets/svg/person.svg").getroot()
    group = root[0]
    swing = math.sin(pose*math.tau/8)
    group[0].set("d", f"M226 345l{-32+32*swing:.1f} 130m{92-32*swing:.1f}-130 {35-32*swing:.1f} 130")
    group[1].set("d", f"M187 244l{-56-32*swing:.1f} {100-12*abs(swing):.1f}m{194+32*swing:.1f} {-100+12*abs(swing):.1f} {53+32*swing:.1f} {98-12*abs(swing):.1f}")
    mouth = root[-1]
    mouth.set("d", "M240 173q16 20 32 0q-16-12-32 0" if speaking else "M234 170q22 27 44 0" if expression=="happy" else "M234 183q22-27 44 0" if expression=="worried" else "M234 175h44")
    if speaking:
        mouth.set("fill","#253748")
    if blink:
        for eye in root[1]:
            eye.set("r","2")
    return Image.open(BytesIO(resvg_py.svg_to_bytes(svg_string=ET.tostring(root,encoding="unicode")))).convert("RGBA")


@lru_cache(maxsize=12)
def custom_sprite(asset, folder):
    path = (Path(folder) / f"{asset}.png").resolve()
    if not path.is_relative_to(Path(folder).resolve()):
        raise ValueError("Recurso fora da biblioteca.")
    with Image.open(path) as source:
        image = source.convert("RGBA")
        image.thumbnail((512,512),Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA",(512,512))
        canvas.alpha_composite(image,((512-image.width)//2,(512-image.height)//2))
        return canvas


def transition_frame(previous, current, kind, frame, count):
    if previous is None or kind=="cut" or count==0 or frame>=count:
        return current
    amount = (frame+1)/count
    amount = amount*amount*(3-2*amount)
    if kind=="crossfade":
        return Image.blend(previous,current,amount)
    width = round(current.width*amount)
    result = previous.copy()
    if kind=="wipe":
        result.paste(current.crop((0,0,width,current.height)),(0,0))
    else:
        result.paste(current,(current.width-width,0))
    return result


@lru_cache(maxsize=6)
def background(kind):
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS[kind])
    draw = ImageDraw.Draw(image)
    rng = random.Random(80)
    if kind in ("space", "city"):
        for _ in range(75):
            x, y = rng.randrange(WIDTH), rng.randrange(150, 1390)
            radius = rng.choice((2, 3, 4))
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="#b8ccd6")
    if kind != "space":
        floor = {"ocean": "#10384b", "snow": "#dce8e9", "city": "#192d43", "dusk": "#8c7666", "studio": "#a8b7a6"}[kind]
        draw.ellipse((-450, 1190, 1550, 2200), fill=floor)
    if kind == "ocean":
        for y in range(350, 1250, 220):
            draw.arc((-300, y, 1400, y+430), 190, 340, fill="#33758c", width=8)
    return image


def transform(element, time_seconds):
    phase = time_seconds * element.speed
    dx = dy = angle = 0.0
    if element.motion == "bob":
        dy = math.sin(phase * 1.5) * element.amplitude
    elif element.motion in ("drift", "walk"):
        dx = math.sin(phase * .35) * element.amplitude * 2
        dy = math.sin(phase * (6 if element.motion == "walk" else 1)) * element.amplitude * .2
        angle = math.sin(phase * 3) * 2 if element.motion == "walk" else 0
    elif element.motion == "orbit":
        dx = math.cos(phase) * element.amplitude
        dy = math.sin(phase) * element.amplitude
    elif element.motion == "spin":
        angle = phase * 8
    return element.x + dx, element.y + dy, angle


def font(size, bold=False):
    windows = Path("C:/Windows/Fonts") / ("segoeuib.ttf" if bold else "segoeui.ttf")
    if windows.is_file():
        return ImageFont.truetype(str(windows), size)
    return ImageFont.truetype("DejaVuSans.ttf", size)


class SceneRenderer:
    def __init__(self, scene, index, count, language="PT", asset_folder=None):
        self.scene = scene
        self.asset_folder = asset_folder
        self.elements = scene.elements or default_elements(scene.background)
        self.base = background(scene.background)
        # Titles remain fixed while the scene camera moves.
        self.overlay = Image.new("RGBA", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(self.overlay)
        label = "HIPÓTESE" if language == "PT" else "HYPOTHESIS"
        draw.text((78, 155), f"{label}  /  {index+1:02d} — {count:02d}", font=font(29), fill="#edf1ea", stroke_width=1, stroke_fill="#243344")
        lines = textwrap.wrap(scene.title, width=25, break_long_words=True)
        for line_index, line in enumerate(lines[:3]):
            draw.text((76, 215+line_index*76), line, font=font(62, True), fill="#ffffff", stroke_width=2, stroke_fill="#243344")

    def frame(self, local_frame, speaking=False):
        scene = self.scene
        time_seconds = local_frame / FPS
        progress = local_frame / max(1, scene.frames-1)
        # Cubic smoothstep for camera changes; constant phase for recurring motion.
        eased = progress * progress * (3-2*progress)
        zoom = scene.camera.zoom_start + (scene.camera.zoom_end-scene.camera.zoom_start)*eased
        image = self.base.copy().convert("RGBA")
        for item in self.elements:
            if item.asset.startswith("asset_"):
                source = custom_sprite(item.asset,self.asset_folder)
            elif item.asset=="person":
                pose = int(time_seconds*item.speed*8)%8 if item.motion=="walk" else 0
                source = person_pose(item.expression,pose,speaking and local_frame%6<3,local_frame%110<3)
            else:
                source = sprite(item.asset, item.expression)
            x, y, angle = transform(item, time_seconds)
            size = round(420 * item.scale * zoom)
            layer = source.resize((size, size), Image.Resampling.BICUBIC)
            if angle:
                layer = layer.rotate(angle, Image.Resampling.BICUBIC, expand=True)
            opacity=item.opacity_start+(item.opacity_end-item.opacity_start)*eased
            if opacity<1:
                layer.putalpha(layer.getchannel("A").point(lambda value:round(value*opacity)))
            px = (x-.5)*WIDTH*zoom+WIDTH*.5+scene.camera.pan_x*WIDTH*eased
            py = (y-.5)*HEIGHT*zoom+HEIGHT*.5+scene.camera.pan_y*HEIGHT*eased
            image.alpha_composite(layer, (round(px-layer.width/2), round(py-layer.height/2)))
        image.alpha_composite(self.overlay)
        return image.convert("RGB")

    def export_svg(self, destination):
        root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=str(WIDTH), height=str(HEIGHT), viewBox="0 0 1080 1920")
        ET.SubElement(root, "rect", width="1080", height="1920", fill=COLORS[self.scene.background])
        for item in self.elements:
            if item.asset.startswith("asset_"):
                png = BytesIO()
                custom_sprite(item.asset,self.asset_folder).save(png,"PNG")
                ET.SubElement(root,"image",x=str(item.x*WIDTH-210*item.scale),y=str(item.y*HEIGHT-210*item.scale),width=str(420*item.scale),height=str(420*item.scale),href="data:image/png;base64,"+base64.b64encode(png.getvalue()).decode())
                continue
            group = ET.SubElement(root, "g", transform=f"translate({item.x*WIDTH-210*item.scale} {item.y*HEIGHT-210*item.scale}) scale({420*item.scale/512})")
            asset = ET.parse(ROOT / "assets" / "svg" / f"{item.asset}.svg").getroot()
            for child in asset:
                group.append(child)
        ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)
