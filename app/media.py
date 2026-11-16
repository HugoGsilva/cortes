"""ffmpeg e ffprobe. Um processo por vez; quem chama serializa."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.silence import parse_silence_log
from app.windows import is_vertical, output_fps


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int
    height: int
    fps: int

    @property
    def vertical(self) -> bool:
        return is_vertical(self.width, self.height)


def probe(path: Path) -> Probe:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate:stream_tags=rotate:stream_side_data=rotation",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(_tail(proc.stderr) or "ffprobe não leu o arquivo")
    data = json.loads(proc.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    video = next(
        (stream for stream in data.get("streams") or [] if stream.get("codec_type") == "video"),
        None,
    )
    if video is None or duration <= 0:
        raise RuntimeError("o arquivo não tem vídeo com duração")
    width = int(video["width"])
    height = int(video["height"])
    rotate = _rotation(video)
    if abs(rotate) % 180 == 90:
        width, height = height, width
    return Probe(duration, width, height, output_fps(_frame_rate(video.get("r_frame_rate"))))


def detect_silences(path: Path, *, noise_db: int = -35, min_silence: float = 0.4) -> list[tuple[float, float]]:
    # -vn: só o áudio. Decodificar a imagem aqui não muda o corte e custa CPU.
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"silencedetect=n={noise_db}dB:d={min_silence}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if proc.returncode != 0:
        raise RuntimeError(_tail(proc.stderr) or "silencedetect falhou")
    duration = probe(path).duration
    return parse_silence_log(proc.stderr, duration)


def extract_wav(source: Path, dest: Path, start: float, length: float) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source),
            "-t",
            f"{length:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        timeout=300,
    )


def encode_clip(
    source: Path,
    dest: Path,
    srt: Path | None,
    *,
    start: float,
    length: float,
    vertical: bool,
    fps: int,
    threads: int = 2,
) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source),
            "-t",
            f"{length:.3f}",
            "-vf",
            video_filter(srt, vertical),
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-maxrate",
            "1800k",
            "-bufsize",
            "3600k",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            str(threads),
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(dest),
        ],
        timeout=900,
    )


def video_filter(srt: Path | None, vertical: bool) -> str:
    if vertical:
        geom = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
    else:
        # Largura par. O centro do 16:9 vira 9:16 em 720p, que é o quadro barato de Shorts.
        geom = "crop=trunc(ih*9/16/2)*2:trunc(ih/2)*2:(iw-trunc(ih*9/16/2)*2)/2:0,scale=720:1280:flags=fast_bilinear"
    if srt is None or not srt.exists() or srt.stat().st_size == 0:
        return geom
    path = str(srt).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    style = "FontName=DejaVu Sans,FontSize=16,Outline=2,Shadow=0,Alignment=2,MarginV=64"
    return f"{geom},subtitles='{path}':force_style='{style}'"


def _rotation(stream: dict) -> int:
    tags = stream.get("tags") or {}
    if tags.get("rotate"):
        return int(tags["rotate"])
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(side["rotation"])
    return 0


def _frame_rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0
    num, _, den = value.partition("/")
    if not den:
        return float(num)
    den_f = float(den)
    if den_f == 0:
        return 0
    return float(num) / den_f


def _run(cmd: list[str], timeout: int) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(_tail(proc.stderr) or "ffmpeg falhou")


def _tail(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-3:])
