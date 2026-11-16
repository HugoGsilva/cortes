"""API mínima: sobe um vídeo, acompanha a fila, baixa os clipes."""

from __future__ import annotations

import hmac
import os
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app.worker import Store, remove_job_files, run_forever

_ID = re.compile(r"^[a-f0-9]{32}$")
_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".ts"}

store: Store | None = None
data_dir = Path(os.environ.get("DATA_DIR", "/data"))


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global store
    _require_token()
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir / "cortes.db")
    threading.Thread(target=run_forever, args=(store, data_dir), daemon=True).start()
    yield


app = FastAPI(title="cortes", docs_url=None, redoc_url=None, lifespan=_lifespan)


def _require_token() -> str:
    token = os.environ.get("TOKEN", "")
    if len(token) < 16:
        raise RuntimeError("defina TOKEN com pelo menos 16 caracteres")
    return token


def _auth(authorization: str | None = Header(default=None)) -> None:
    expected = _require_token()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if len(supplied) != len(expected) or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="token inválido")


def _job_or_404(job_id: str) -> dict:
    if store is None or not _ID.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="job não encontrado")
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@app.get("/health")
def health() -> dict:
    return {"ok": True, "busy": bool(store and store.active_count())}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/jobs")
def list_jobs(_auth_ok: None = Depends(_auth)) -> dict:
    assert store is not None
    return {"jobs": store.list_jobs()}


@app.post("/jobs", status_code=202)
async def create_job(file: UploadFile, _auth_ok: None = Depends(_auth)) -> dict:
    assert store is not None
    if store.active_count() >= 1:
        raise HTTPException(status_code=429, detail="já tem um vídeo na fila; espere este terminar")
    job_id = uuid.uuid4().hex
    folder = data_dir / "jobs" / job_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _SUFFIXES:
        suffix = ".mp4"
    dest = folder / f"source{suffix}"
    limit = int(os.environ.get("MAX_UPLOAD_MB", "1500")) * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="arquivo passa do limite")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="arquivo vazio")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    store.insert(job_id, Path(file.filename or dest.name).name)
    return {"id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, _auth_ok: None = Depends(_auth)) -> dict:
    return _job_or_404(job_id)


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, _auth_ok: None = Depends(_auth)) -> dict:
    job = _job_or_404(job_id)
    if job["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="esse vídeo ainda está na fila")
    assert store is not None
    remove_job_files(data_dir, job_id)
    store.delete(job_id)
    return {"ok": True}


@app.get("/jobs/{job_id}/clips/{index}/video")
def clip_video(job_id: str, index: int, _auth_ok: None = Depends(_auth)) -> FileResponse:
    path = _clip_path(job_id, index, ".mp4")
    return FileResponse(path, media_type="video/mp4", filename=f"{index:03}.mp4")


@app.get("/jobs/{job_id}/clips/{index}/srt")
def clip_srt(job_id: str, index: int, _auth_ok: None = Depends(_auth)) -> FileResponse:
    path = _clip_path(job_id, index, ".srt")
    return FileResponse(path, media_type="application/x-subrip", filename=f"{index:03}.srt")


def _clip_path(job_id: str, index: int, suffix: str) -> Path:
    _job_or_404(job_id)
    if index < 0 or index > 999:
        raise HTTPException(status_code=404, detail="clipe não encontrado")
    path = data_dir / "jobs" / job_id / "clips" / f"{index:03}{suffix}"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="clipe não encontrado")
    return path
