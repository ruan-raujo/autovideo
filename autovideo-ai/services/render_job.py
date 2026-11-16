"""Isolated media pipeline with verified NVENC or bounded CPU encoding."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import traceback
import wave

import numpy as np
import psutil

from animation.renderer import FPS, HEIGHT, WIDTH, SceneRenderer, transition_frame
from services.audio_effects import mix_effects
from services.encoding import select_encoder
from models.schemas import QueueSettings, ScriptInput
from services.media_tools import MediaError, process_flags
from services.narration import load_voice, synthesize_scene, write_wav
from services.subtitles import write_subtitles

PROGRESS_CONTEXT = None


def progress(workspace, state, percent, message):
    if PROGRESS_CONTEXT:
        root, index, total, language = PROGRESS_CONTEXT
        workspace = root
        percent = round((index*100+percent)/total)
        message = f"{language} · {message}"
    payload = {"state": state, "progress": percent, "message": message}
    temporary = workspace / "progress.tmp"
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(workspace / "progress.json")
    except PermissionError:
        pass  # A UI reader may briefly hold the file on Windows.


def run(args, workspace, log, timeout=120):
    result = subprocess.run(args, cwd=workspace, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=log, timeout=timeout, **process_flags())
    if result.returncode:
        raise MediaError("O FFmpeg encontrou um erro. Consulte o log deste trabalho.")


def validate_video(path, ffprobe, ffmpeg, workspace, log, language="PT"):
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30, **process_flags(),
    )
    if result.returncode:
        raise MediaError("FFprobe não conseguiu ler o vídeo final.")
    metadata = json.loads(result.stdout)
    video = next((s for s in metadata["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in metadata["streams"] if s["codec_type"] == "audio"), None)
    subtitles = next((s for s in metadata["streams"] if s["codec_type"] == "subtitle"), None)
    expected = video and video["codec_name"] == "h264" and video["width"] == 1080 and video["height"] == 1920
    expected = expected and video.get("avg_frame_rate") == "30/1" and int(video.get("nb_frames", 0)) == 2400
    expected = expected and abs(float(video["duration"])-80) < .001 and abs(float(metadata["format"]["duration"])-80) < .001
    expected = expected and audio and audio["codec_name"] == "aac" and audio.get("tags", {}).get("language") == ("por" if language == "PT" else "eng")
    expected = expected and abs(float(audio["duration"])-80) < .025 and subtitles and subtitles["codec_name"] == "mov_text"
    if not expected:
        raise MediaError("O vídeo falhou na validação: são exigidos 80s, 2400 quadros, 1080×1920, H.264, AAC e legendas PT.")
    # Decode every video frame and the entire audio, not just container metadata.
    run([str(ffmpeg), "-v", "error", "-xerror", "-threads", "2", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], workspace, log, timeout=300)
    metadata["validation"] = {"passed": True, "full_decode": True, "burned_subtitles": True, "language": language, "word_alignment": "piper_phonemes"}
    return metadata


def render_language(request, workspace):
    start = time.monotonic()
    script = ScriptInput.model_validate(request["script"])
    settings = QueueSettings.model_validate(request["settings"])
    ffmpeg, ffprobe = request["ffmpeg"], request["ffprobe"]
    language = script.language
    with (workspace / "render.log").open("w", encoding="utf-8") as log:
        progress(workspace, "synthesizing", 2, f"Carregando a voz local {language}.")
        voice = load_voice(Path(request["voice"]), settings.cpu_threads)
        rate = voice.config.sample_rate
        timeline = np.zeros(80 * rate, dtype=np.int16)
        words, fitting = [], []
        frame_offset = 0
        for index, scene in enumerate(script.scenes):
            duration = scene.frames/FPS
            audio, timings, tempo, raw_duration = synthesize_scene(voice, scene.narration, duration, index+1)
            raw = workspace / f"scene_{index+1:03}_raw.wav"
            adjusted = workspace / f"scene_{index+1:03}_voice.wav"
            write_wav(raw, audio, rate)
            run([ffmpeg, "-v", "warning", "-y", "-i", str(raw), "-af", f"atempo={tempo:.8f}", "-ac", "1", "-ar", str(rate), str(adjusted)], workspace, log)
            with wave.open(str(adjusted), "rb") as wav:
                fitted = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            scene_start = round(frame_offset/FPS*rate)
            speech_start = scene_start + round(.15*rate)
            scene_end = round((frame_offset+scene.frames)/FPS*rate)
            if speech_start+len(fitted) > scene_end-round(.1*rate):
                raise MediaError(f"Cena {index+1}: ajuste de voz excedeu o espaço disponível. Reduza o texto; nenhuma palavra foi cortada.")
            timeline[speech_start:speech_start+len(fitted)] = fitted
            for word in timings:
                word["start"] += frame_offset/FPS
                word["end"] += frame_offset/FPS
                word["scene"] = index+1
                words.append(word)
            fitting.append({"scene": index+1, "raw_seconds": raw_duration, "tempo": tempo, "slot_seconds": duration, "speech_seconds": len(fitted)/rate})
            frame_offset += scene.frames
            progress(workspace, "synthesizing", 3+round(15*(index+1)/len(script.scenes)), f"Narração da cena {index+1}/{len(script.scenes)} pronta.")
        del voice
        speech_activity = np.array([np.max(np.abs(timeline[round(i/30*rate):round((i+1)/30*rate)].astype(np.int32)))>500 for i in range(2400)])
        timeline = mix_effects(timeline,rate,[s.frames for s in script.scenes],settings.music_enabled,settings.sfx_enabled)
        write_wav(workspace / "narration_source.wav", timeline, rate)
        run([ffmpeg, "-v", "warning", "-y", "-i", "narration_source.wav", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ar", "48000", "-ac", "1", "narration.wav"], workspace, log)
        write_subtitles(words, workspace, settings.subtitle_font_size)
        (workspace / "word_timings.json").write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
        (workspace / "narration_fit.json").write_text(json.dumps(fitting, indent=2), encoding="utf-8")
        filename = f"video_{request['job_id'][:8]}_{language}.mp4"
        output = workspace / filename
        encoder = select_encoder(ffmpeg,settings.encoder)
        codec_options = ["-preset","p4","-rc","vbr","-cq","23","-b:v","0"] if encoder=="h264_nvenc" else ["-preset","veryfast","-crf","20"]
        args = [ffmpeg, "-v", "warning", "-nostdin", "-y", "-threads", str(settings.cpu_threads),
                "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", "30", "-i", "pipe:0",
                "-i", "narration.wav", "-i", "subtitles.srt", "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
                "-vf", "ass=subtitles.ass", "-filter_threads", "1", "-c:v", encoder, *codec_options,
                "-threads", str(settings.cpu_threads), "-pix_fmt", "yuv420p", "-frames:v", "2400",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-c:s", "mov_text",
                "-metadata:s:a:0", f"language={'por' if language == 'PT' else 'eng'}", "-metadata:s:s:0", f"language={'por' if language == 'PT' else 'eng'}",
                "-t", "80", "-movflags", "+faststart", filename]
        process = subprocess.Popen(args, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log, **process_flags())
        written = 0
        previous_frame = None
        try:
            for index, scene in enumerate(script.scenes):
                renderer = SceneRenderer(scene, index, len(script.scenes), language, request.get("asset_folder"))
                renderer.export_svg(workspace / f"scene_{index+1:03}.svg")
                for local_frame in range(scene.frames):
                    frame = renderer.frame(local_frame,bool(speech_activity[written]))
                    frame = transition_frame(previous_frame,frame,scene.transition,local_frame,min(scene.transition_frames,scene.frames))
                    if local_frame == min(30, scene.frames-1):
                        frame.save(workspace / f"scene_{index+1:03}_preview.jpg", quality=85)
                    process.stdin.write(frame.tobytes())
                    written += 1
                    if written % 30 == 0:
                        progress(workspace, "rendering", 20+round(written/2400*70), f"Renderizando quadro {written}/2400 · cena {index+1}/{len(script.scenes)}.")
                previous_frame = frame
            process.stdin.close()
            if process.wait(timeout=120):
                raise MediaError("O FFmpeg não concluiu a codificação. Consulte o log do trabalho.")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        progress(workspace, "validating", 94, "FFprobe verificando duração, quadros, resolução e áudio.")
        metadata = validate_video(output, ffprobe, ffmpeg, workspace, log, language)
        metadata["render_seconds"] = round(time.monotonic()-start, 2)
        metadata["frames_written"] = written
        metadata["subtitle_font_size"] = settings.subtitle_font_size
        metadata["encoder"] = encoder
        metadata["audio_effects"] = {"music":settings.music_enabled,"sfx":settings.sfx_enabled,"source":"original_procedural"}
        (workspace / "validation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        (workspace / "result.json").write_text(json.dumps({"filename": filename, "metadata": metadata}), encoding="utf-8")
        progress(workspace, "validating", 99, "Arquivo validado; publicando o MP4 local.")


def render(request, workspace):
    global PROGRESS_CONTEXT
    scripts = request.get("scripts") or {request["script"]["language"]: request["script"]}
    languages = list(scripts)
    videos = {}
    for index, language in enumerate(languages):
        PROGRESS_CONTEXT = (workspace, index, len(languages), language)
        folder = workspace / language
        folder.mkdir()
        local_request = dict(request, script=scripts[language], voice=request.get("voices", {}).get(language, request.get("voice")))
        render_language(local_request, folder)
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        result["filename"] = f"{language}/{result['filename']}"
        videos[language] = result
    PROGRESS_CONTEXT = None
    result = {"videos": videos}
    if len(videos) == 1:
        result.update(next(iter(videos.values())))  # Preserve the stage-2 supervisor contract.
    (workspace / "result.json").write_text(json.dumps(result), encoding="utf-8")


def stop_when_owner_exits(request):
    """Avoid orphaned encoders when the API process is forcibly terminated."""
    while True:
        try:
            owner = psutil.Process(request["owner_pid"])
            if abs(owner.create_time()-request["owner_created"]) > .01:
                raise psutil.NoSuchProcess(request["owner_pid"])
        except psutil.NoSuchProcess:
            for child in psutil.Process().children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            os._exit(2)
        time.sleep(.25)


if __name__ == "__main__":
    workspace = Path(sys.argv[1]).resolve()
    try:
        request = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
        threading.Thread(target=stop_when_owner_exits, args=(request,), daemon=True, name="media-owner-watchdog").start()
        render(request, workspace)
    except Exception as error:
        traceback.print_exc()
        message = str(error) if isinstance(error, MediaError) else "Falha na renderização. Consulte o log local do trabalho."
        (workspace / "failure.json").write_text(json.dumps({"message": message}, ensure_ascii=False), encoding="utf-8")
        sys.exit(1)
