"""SSML builder for Azure TTS responses."""
from __future__ import annotations

import os
import re


def build_ssml(text: str, lang_long: str) -> str:
    rate = os.getenv("TTS_PROSODY_RATE", "fast")
    pitch = os.getenv("TTS_PROSODY_PITCH", "medium")
    volume = os.getenv("TTS_PROSODY_VOLUME", "medium")
    style = os.getenv("TTS_STYLE", "chat")
    degree = os.getenv("TTS_STYLE_DEGREE", "1.0")
    cleaned = re.sub(r"[\U00010000-\U0010FFFF]", "", text)
    return (
        f"<speak version=\"1.0\" xml:lang=\"{lang_long}\" xmlns:mstts=\"http://www.w3.org/2001/mstts\">"
        f"<mstts:express-as style=\"{style}\" styledegree=\"{degree}\">"
        f"<prosody rate=\"{rate}\" pitch=\"{pitch}\" volume=\"{volume}\">"
        f"{cleaned}"
        f"</prosody></mstts:express-as></speak>"
    )
