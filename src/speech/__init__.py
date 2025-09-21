"""Speech utilities: humanization, time helpers, SSML, and event wiring."""

from .humanize import humanize_slots, replace_time_with_words, summarize_hours
from .time_utils import format_time, normalize_lang_tag
from .ssml import build_ssml
from .events import register_thinking_bridge

__all__ = [
    "humanize_slots",
    "replace_time_with_words",
    "summarize_hours",
    "format_time",
    "normalize_lang_tag",
    "build_ssml",
    "register_thinking_bridge",
]
