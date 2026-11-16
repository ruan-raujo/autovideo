"""Inspect decoded output: motion, audio energy, caption pixels and contact sheet."""
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import Config
from services.media_tools import executable, process_flags


def main():
    ffmpeg=str(executable("ffmpeg",Config()))
    report=json.loads((ROOT/"tests/artifacts/full-validation.json").read_text(encoding="utf-8"))
    sheet=Image.new("RGB",(1080,520*len(report["videos"])),"#172332")
    draw=ImageDraw.Draw(sheet)
    checks=[]
    for row,item in enumerate(report["videos"]):
        path=Path(item["path"])
        def frame(seconds):
            result=subprocess.run([ffmpeg,"-v","error","-ss",str(seconds),"-i",str(path),"-frames:v","1","-f","image2pipe","-vcodec","png","pipe:1"],capture_output=True,timeout=45,check=True,**process_flags())
            return Image.open(BytesIO(result.stdout)).convert("RGB")
        timings=json.loads(path.with_suffix(".word_timings.json").read_text(encoding="utf-8"))
        word=timings[min(2,len(timings)-1)]
        timestamp=(word["start"]+word["end"])/2
        caption=frame(timestamp)
        pixels=np.asarray(caption)[1450:1690].astype(np.int16)
        gold=int(((pixels[:,:,0]>190)&(pixels[:,:,1]>160)&(pixels[:,:,2]<185)&(pixels[:,:,0]-pixels[:,:,2]>50)).sum())
        assert gold>40,f"No highlighted caption pixels in {path.name}"
        early=np.asarray(frame(1.0))[450:1350].astype(np.int16)
        later=np.asarray(frame(2.0))[450:1350].astype(np.int16)
        movement=float(np.abs(early-later).mean())
        assert movement>.02,f"No visible motion in {path.name}"
        audio=subprocess.run([ffmpeg,"-v","error","-i",str(path),"-map","0:a:0","-ac","1","-ar","8000","-f","s16le","pipe:1"],capture_output=True,check=True,timeout=45,**process_flags())
        samples=np.frombuffer(audio.stdout,dtype=np.int16).astype(np.float32)
        rms=float(np.sqrt(np.mean(samples**2)))
        assert len(samples)>=80*8000-200 and rms>100,f"Missing/quiet audio in {path.name}"
        checks.append({"file":path.name,"motion_mean_difference":round(movement,3),"highlight_pixels":gold,"audio_rms":round(rms,1),"audio_samples":len(samples)})
        for column,seconds in enumerate((timestamp,22,44,66)):
            image=caption if column==0 else frame(seconds)
            image.thumbnail((270,480),Image.Resampling.LANCZOS)
            sheet.paste(image,(column*270,row*520+30))
            draw.text((column*270+8,row*520+8),f"{path.stem} / {seconds:.1f}s",fill="white")
    sheet.save(ROOT/"tests/artifacts/acceptance-contact-sheet.jpg",quality=90)
    (ROOT/"tests/artifacts/decoded-inspection.json").write_text(json.dumps({"passed":True,"videos":checks},indent=2),encoding="utf-8")
    print(json.dumps(checks,indent=2))


if __name__=="__main__":
    main()
