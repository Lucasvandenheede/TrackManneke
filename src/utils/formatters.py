import re

def format_time_ms(milliseconds: int) -> str:
    total_seconds = milliseconds // 1000
    remaining_ms = milliseconds % 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}.{remaining_ms:03d}"


def format_rank(rank: int) -> str:
    return f"#{rank}"

_TM_FORMAT_RE = re.compile(r"\$(?:F[0-9A-Fa-f]{2}|[0-9A-Fa-f]{3}|[a-zA-Z])")

def strip_tm_formatting(text: str) -> str:

    if not text:
        return text
    return _TM_FORMAT_RE.sub("", text).strip()
