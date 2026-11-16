"""Original procedural ambience and scene whooshes; no downloaded recordings."""
import numpy as np


def mix_effects(narration, rate, scene_frames, music=False, sfx=False):
    if not music and not sfx:
        return narration
    length = len(narration)
    mixed = narration.astype(np.float32)
    if music:
        time = np.arange(length,dtype=np.float32)/rate
        bed = np.zeros(length,dtype=np.float32)
        for frequency in (130.81,196.0,261.63):
            bed += np.sin(time*(2*np.pi*frequency))*180
        # Duck under speech using 100 ms blocks; fade ends to prevent clicks.
        block = max(1,rate//10)
        padded = np.pad(np.abs(mixed),(0,(-length)%block))
        envelope = np.repeat(padded.reshape(-1,block).max(axis=1)>350,block)[:length]
        bed *= np.where(envelope,.32,1.0)
        fade = min(rate*2,length//2)
        bed[:fade] *= np.linspace(0,1,fade)
        bed[-fade:] *= np.linspace(1,0,fade)
        mixed += bed
    if sfx:
        rng = np.random.default_rng(80)
        offset = 0
        for frames in scene_frames[:-1]:
            offset += frames
            start = round(offset/30*rate)
            size = min(round(.24*rate),length-start)
            noise = rng.normal(0,1,size).astype(np.float32)
            smooth = np.convolve(noise,np.ones(16,dtype=np.float32)/16,mode="same")
            mixed[start:start+size] += smooth*np.sin(np.linspace(0,np.pi,size))**2*1000
    return np.clip(mixed,-32768,32767).astype(np.int16)
