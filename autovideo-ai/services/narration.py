"""Piper phoneme durations provide word timing without another AI model."""
import json
import re
import wave
import unicodedata
from difflib import SequenceMatcher

import numpy as np
import onnxruntime
from piper import PiperVoice
from piper.config import PiperConfig, SynthesisConfig

from services.media_tools import MediaError


def align_linked_words(voice, words, phone_samples):
    """Map synthesized phones to text words, including linked English function words."""
    ignored = set(" ^$.,?!;:ˈˌːˑ\n—–\"'“”‘’()[]")
    expected, owners = [], []
    for index, word in enumerate(words):
        for sentence in voice.phonemize(word):
            for phone in sentence:
                if phone not in ignored:
                    expected.append(phone)
                    owners.append(index)
    actual = [(phone, start, end) for phone, start, end in phone_samples if phone not in ignored]
    mapped = [[] for _ in words]
    matcher = SequenceMatcher(a=expected, b=[item[0] for item in actual], autojunk=False)
    for kind, left, right, start, stop in matcher.get_opcodes():
        for position in range(start, stop):
            if kind == "equal":
                reference = left+position-start
            elif right > left:
                reference = min(right-1, left+(position-start)*(right-left)//max(1,stop-start))
            else:
                reference = max(0, left-1)
            if owners:
                mapped[owners[reference]].append(actual[position][1:])
    if any(not values for values in mapped):
        return None
    return [(values[0][0], values[-1][1]) for values in mapped]


def load_voice(path, threads):
    onnxruntime.set_seed(42)
    np.random.seed(42)
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    config = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
    voice = PiperVoice(
        session=onnxruntime.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"]),
        config=PiperConfig.from_dict(config),
    )
    return voice


def synthesize_scene(voice, text, duration, scene_index):
    words = []
    for token in text.split():
        if not any(char.isalnum() for char in token) and words:
            words[-1] += token
        else:
            words.append(token)
    samples, spans, phone_samples = [], [], []
    sample_offset = 0
    for chunk in voice.synthesize(text, syn_config=SynthesisConfig(noise_scale=.5, noise_w_scale=.333), include_alignments=True):
        if not chunk.phoneme_alignments:
            raise MediaError("A voz não oferece alinhamento temporal. Execute novamente instalar_midia.bat.")
        start = None
        cursor = sample_offset
        last_sound = cursor
        for part in chunk.phoneme_alignments:
            symbol = part.phoneme
            stop = cursor + int(part.num_samples)
            phone_samples.append((symbol, cursor, stop))
            if symbol == " " or symbol in ("$", ".", ",", "?", "!", ";", ":"):
                if start is not None:
                    spans.append((start, last_sound))
                    start = None
            elif symbol != "^":
                if start is None:
                    start = cursor
                last_sound = stop
            cursor = stop
        if start is not None:
            spans.append((start, last_sound))
        audio = chunk.audio_int16_array
        samples.append(audio)
        sample_offset += len(audio)
    if not samples:
        raise MediaError(f"Cena {scene_index}: a voz não produziu áudio.")
    if len(words) != len(spans):
        spans = align_linked_words(voice, words, phone_samples) if hasattr(voice, "phonemize") else None
        if spans is None:
            raise MediaError(f"Cena {scene_index}: não foi possível alinhar as palavras. Escreva números e abreviações por extenso e evite palavras hifenizadas.")
    audio = np.concatenate(samples)
    sample_rate = voice.config.sample_rate
    raw_duration = len(audio)/sample_rate
    target = duration-.4
    tempo = max(.92, min(1.12, raw_duration/target))
    if raw_duration / tempo > target + .005:
        raise MediaError(f"Cena {scene_index}: narração com {raw_duration:.1f}s não cabe em {duration:.1f}s sem acelerar demais. Encurte a fala ou aumente a duração da cena.")
    if raw_duration / tempo < duration*.2:
        raise MediaError(f"Cena {scene_index}: a fala está curta demais para a duração. Desenvolva o texto ou redistribua os tempos.")
    timings = [
        {"word": word, "start": .15 + start/sample_rate/tempo, "end": .15+end/sample_rate/tempo}
        for word, (start, end) in zip(words, spans, strict=True)
    ]
    return audio, timings, tempo, raw_duration


def write_wav(path, audio, sample_rate):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(audio.astype(np.int16).tobytes())
