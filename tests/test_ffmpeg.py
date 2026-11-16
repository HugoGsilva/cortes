import shutil
import subprocess
from pathlib import Path

import pytest

from app.media import detect_silences, encode_clip, probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg ausente")


def test_silence_and_vertical_encode(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=12",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
            "-map", "0:v", "-map", "[a]", "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(source),
        ],
        check=True,
    )
    info = probe(source)
    assert info.duration > 10
    assert info.vertical is False
    pauses = detect_silences(source, noise_db=-30, min_silence=0.3)
    assert pauses

    srt = tmp_path / "000.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nolá\n", encoding="utf-8")
    dest = tmp_path / "out.mp4"
    encode_clip(source, dest, srt, start=0, length=4, vertical=False, fps=15, threads=1)
    assert dest.stat().st_size > 1000
