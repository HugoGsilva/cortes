"""Lê o texto do filtro silencedetect. Sem subprocess."""

from __future__ import annotations

import re

_START = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_END = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


def parse_silence_log(text: str, duration: float | None = None) -> list[tuple[float, float]]:
    starts = [float(value) for value in _START.findall(text)]
    ends = [float(value) for value in _END.findall(text)]
    pauses: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        if index < len(ends) and ends[index] > start:
            pauses.append((start, ends[index]))
        elif duration is not None and duration > start:
            pauses.append((start, duration))
    return pauses
