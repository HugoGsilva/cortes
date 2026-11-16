"""Escolhe os intervalos dos clipes. Não chama ffmpeg nem carrega modelo."""

from __future__ import annotations


def merge_silences(
    silences: list[tuple[float, float]], duration: float
) -> list[tuple[float, float]]:
    items = sorted(
        (max(0.0, start), min(duration, end))
        for start, end in silences
        if end > start
    )
    merged: list[tuple[float, float]] = []
    for start, end in items:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def is_vertical(width: int, height: int, rotate: int = 0) -> bool:
    if abs(rotate) % 180 == 90:
        width, height = height, width
    return height >= width


def output_fps(source_fps: float) -> int:
    """Acima de 30 quadros só gasta CPU. Abaixo disso, mantém o original."""
    if source_fps <= 0 or source_fps > 30:
        return 30
    return max(15, int(round(source_fps)))


def plan_windows(
    duration: float,
    silences: list[tuple[float, float]],
    *,
    target: float = 50.0,
    max_len: float = 60.0,
    min_len: float = 12.0,
    max_clips: int = 80,
) -> list[tuple[float, float]]:
    """Devolve pares (início, fim) em segundos.

    Sem pausa, corta no relógio em `max_len`. Com pausa, fecha o clipe
    no silêncio mais perto de `target`. Descarta a sobra menor que `min_len`.
    """
    if duration < 3:
        return []
    if duration <= max_len:
        return [(0.0, _round(duration))]

    pauses = merge_silences(silences, duration)
    windows: list[tuple[float, float]] = []
    cursor = 0.0
    for _ in range(max_clips * 4):
        if len(windows) >= max_clips or duration - cursor < min_len:
            break
        cursor = _skip_silence(pauses, cursor)
        if duration - cursor < min_len:
            break
        hard = min(duration, cursor + max_len)
        ideal = min(duration, cursor + target)
        cut = _cut_at(pauses, cursor, ideal, hard, min_len)
        end = hard if cut is None else cut
        if end <= cursor:
            cursor = min(duration, cursor + max_len)
            continue
        if end - cursor < min_len:
            end = hard
        windows.append((_round(cursor), _round(min(end, duration))))
        cursor = min(end, duration)
    return windows


def _cut_at(
    pauses: list[tuple[float, float]],
    cursor: float,
    ideal: float,
    hard: float,
    min_len: float,
) -> float | None:
    earliest = cursor + min_len
    best: float | None = None
    best_dist = float("inf")
    for start, _end in pauses:
        if start < earliest or start > hard:
            continue
        dist = abs(start - ideal)
        if dist < best_dist:
            best_dist = dist
            best = start
    return best


def _skip_silence(pauses: list[tuple[float, float]], cursor: float) -> float:
    for start, end in pauses:
        if start - 0.05 <= cursor <= end:
            return end
    return cursor


def _round(value: float) -> float:
    return round(value, 3)
