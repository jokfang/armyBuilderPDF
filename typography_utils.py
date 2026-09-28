from __future__ import annotations

import re


def normalize_bracket_spacing(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\s+([)\]])", r"\1", text)
    text = re.sub(r"([\(\[])\s+", r"\1", text)
    text = re.sub(r"(?<=[^\s\(\[])([\(\[])", r" \1", text)
    text = re.sub(r"([)\]])(?=[^\s)\].,;:!?])", r"\1 ", text)
    return text
