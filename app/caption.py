"""Legenda local. O modelo só entra na memória no primeiro clipe."""

from __future__ import annotations

import os
import threading
from pathlib import Path

_model = None
_lock = threading.Lock()


def transcribe(wav: Path) -> list[tuple[float, float, str]]:
    model = _get_model()
    language = os.environ.get("LANGUAGE", "pt")
    segments, _info = model.transcribe(
        str(wav),
        language=language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    lines: list[tuple[float, float, str]] = []
    for segment in segments:
        text = (segment.text or "").strip()
        if text:
            lines.append((float(segment.start), float(segment.end), text))
    return lines


def write_srt(lines: list[tuple[float, float, str]], dest: Path) -> None:
    blocks: list[str] = []
    for index, (start, end, text) in enumerate(lines, start=1):
        blocks.append(f"{index}\n{_stamp(start)} --> {_stamp(end)}\n{text}\n")
    dest.write_text("\n".join(blocks), encoding="utf-8")


def _get_model():
    global _model
    with _lock:
        if _model is None:
            data = os.environ.get("DATA_DIR", "/data")
            os.environ.setdefault("HF_HOME", str(Path(data) / "models"))
            os.environ.setdefault("HF_HUB_CACHE", os.environ["HF_HOME"])
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                os.environ.get("WHISPER_MODEL", "small"),
                device="cpu",
                compute_type="int8",
                cpu_threads=int(os.environ.get("WHISPER_THREADS", "2")),
                num_workers=1,
            )
        return _model


def _stamp(seconds: float) -> str:
    total = max(0, int(round(seconds * 1000)))
    hours, total = divmod(total, 3_600_000)
    minutes, total = divmod(total, 60_000)
    secs, millis = divmod(total, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
