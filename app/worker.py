"""Fila de um vídeo. Whisper e encode nunca rodam juntos, nem dois vídeos."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.caption import transcribe, write_srt
from app.media import detect_silences, encode_clip, extract_wav, probe
from app.windows import plan_windows


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at REAL NOT NULL,
                    source_name TEXT,
                    duration REAL,
                    clip_total INTEGER DEFAULT 0,
                    clip_done INTEGER DEFAULT 0
                )
                """
            )

    def insert(self, job_id: str, source_name: str) -> None:
        with self.lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO jobs (id, status, created_at, source_name) VALUES (?, 'queued', ?, ?)",
                (job_id, time.time(), source_name),
            )

    def active_count(self) -> int:
        with self.lock, self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
        return int(row["n"])

    def list_jobs(self, limit: int = 20) -> list[dict]:
        with self.lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, job_id: str) -> dict | None:
        with self.lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim(self) -> dict | None:
        with self.lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE jobs SET status = 'running', error = NULL WHERE id = ?", (row["id"],))
        return dict(row)

    def progress(self, job_id: str, done: int, total: int, duration: float) -> None:
        with self.lock, self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET clip_done = ?, clip_total = ?, duration = ? WHERE id = ?",
                (done, total, duration, job_id),
            )

    def finish(self, job_id: str, total: int) -> None:
        with self.lock, self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'done', clip_done = ?, clip_total = ?, error = NULL WHERE id = ?",
                (total, total, job_id),
            )

    def fail(self, job_id: str, message: str) -> None:
        with self.lock, self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'error', error = ? WHERE id = ?",
                (message[:500], job_id),
            )

    def delete(self, job_id: str) -> None:
        with self.lock, self._conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def interrupt_running(self) -> None:
        with self.lock, self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'error', error = 'interrompido pelo reinício' WHERE status = 'running'"
            )

    def expired(self, older_than: float) -> list[str]:
        cutoff = time.time() - older_than
        with self.lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE created_at < ? AND status IN ('done', 'error')",
                (cutoff,),
            ).fetchall()
        return [row["id"] for row in rows]

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def run_forever(store: Store, data_dir: Path) -> None:
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    store.interrupt_running()
    last_cleanup = 0.0
    while True:
        job = store.claim()
        if job is not None:
            _process(store, data_dir, job["id"])
            continue
        now = time.time()
        if now - last_cleanup > 3600:
            _cleanup(store, data_dir)
            last_cleanup = now
        time.sleep(2)


def _process(store: Store, data_dir: Path, job_id: str) -> None:
    folder = data_dir / "jobs" / job_id
    source = _source_file(folder)
    print(f"[cortes] {job_id} iniciou", flush=True)
    try:
        if source is None:
            raise RuntimeError("arquivo de origem sumiu")
        info = probe(source)
        pauses = detect_silences(
            source,
            noise_db=int(os.environ.get("SILENCE_DB", "-35")),
            min_silence=float(os.environ.get("SILENCE_SECONDS", "0.4")),
        )
        windows = plan_windows(
            info.duration,
            pauses,
            target=float(os.environ.get("WINDOW_SECONDS", "50")),
            max_len=float(os.environ.get("MAX_WINDOW_SECONDS", "60")),
            max_clips=int(os.environ.get("MAX_CLIPS", "80")),
        )
        if not windows:
            raise RuntimeError("vídeo curto demais para cortar (mínimo 3 segundos)")
        store.progress(job_id, 0, len(windows), info.duration)
        clips = folder / "clips"
        clips.mkdir(parents=True, exist_ok=True)
        threads = int(os.environ.get("FFMPEG_THREADS", "2"))
        for index, (start, end) in enumerate(windows):
            length = end - start
            wav = clips / f"{index:03}.wav"
            srt = clips / f"{index:03}.srt"
            out = clips / f"{index:03}.mp4"
            extract_wav(source, wav, start, length)
            try:
                lines = transcribe(wav)
            except Exception as exc:
                print(f"[cortes] {job_id} clipe {index} sem legenda: {exc}", flush=True)
                lines = []
            finally:
                wav.unlink(missing_ok=True)
            if lines:
                write_srt(lines, srt)
            encode_clip(
                source,
                out,
                srt if lines else None,
                start=start,
                length=length,
                vertical=info.vertical,
                fps=info.fps,
                threads=threads,
            )
            store.progress(job_id, index + 1, len(windows), info.duration)
            print(f"[cortes] {job_id} clipe {index + 1}/{len(windows)}", flush=True)
        source.unlink(missing_ok=True)
        store.finish(job_id, len(windows))
        print(f"[cortes] {job_id} pronto ({len(windows)} clipes)", flush=True)
    except Exception as exc:
        store.fail(job_id, str(exc))
        print(f"[cortes] {job_id} erro: {exc}", flush=True)


def remove_job_files(data_dir: Path, job_id: str) -> None:
    folder = data_dir / "jobs" / job_id
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()
    folder.rmdir()


def _cleanup(store: Store, data_dir: Path) -> None:
    hours = float(os.environ.get("RETENTION_HOURS", "48"))
    for job_id in store.expired(hours * 3600):
        remove_job_files(data_dir, job_id)
        store.delete(job_id)
        print(f"[cortes] {job_id} expirado", flush=True)


def _source_file(folder: Path) -> Path | None:
    if not folder.exists():
        return None
    for path in folder.iterdir():
        if path.is_file() and path.name.startswith("source"):
            return path
    return None
