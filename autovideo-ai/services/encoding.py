"""Verify the hardware encoder with a real frame before selecting it."""
import subprocess

from services.media_tools import MediaError, process_flags


def select_encoder(ffmpeg, preference="auto"):
    if preference=="cpu":
        return "libx264"
    try:
        result = subprocess.run([str(ffmpeg),"-v","error","-f","lavfi","-i","color=s=1080x1920:r=30:d=0.067",
                                 "-frames:v","2","-c:v","h264_nvenc","-pix_fmt","yuv420p","-f","null","-"],
                                capture_output=True,timeout=30,**process_flags())
        if result.returncode==0:
            return "h264_nvenc"
    except (OSError,subprocess.TimeoutExpired):
        pass
    if preference=="nvenc":
        raise MediaError("NVENC indisponível neste ambiente. Selecione Automático ou CPU.")
    return "libx264"
