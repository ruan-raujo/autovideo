import re


def srt_time(seconds):
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def ass_time(seconds):
    centis = max(0, round(seconds * 100))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    seconds, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centis:02}"


def write_subtitles(words, workspace, font_size):
    # Four words per caption, shorter when punctuation ends a sentence.
    groups, current = [], []
    for word in words:
        current.append(word)
        if len(current) >= 4 or re.search(r"[.!?]$", word["word"]):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H007EE5FF,&H00FFFFFF,&H00201B17,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,110,160,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass, srt = [header], []
    for index, group in enumerate(groups, 1):
        start, end = group[0]["start"], group[-1]["end"]
        text = " ".join(word["word"] for word in group)
        srt.append(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
        karaoke = []
        for position, word in enumerate(group):
            until = group[position+1]["start"] if position+1 < len(group) else end
            duration = max(1, round((until-word["start"])*100))
            # Text has already rejected ASS override characters and backslashes.
            karaoke.append(f"{{\\k{duration}}}{word['word']}")
        ass.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{' '.join(karaoke)}\n")
    (workspace / "subtitles.ass").write_text("".join(ass), encoding="utf-8-sig")
    (workspace / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
    return groups
