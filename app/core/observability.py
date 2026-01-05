# app/core/observability.py
from __future__ import annotations

import json
import logging
import os
import socket
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.settings import OUTPUT_FOLDER

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

def get_request_id() -> str:
    return request_id_ctx.get()

def set_request_id(value: str) -> None:
    request_id_ctx.set(value or "-")


class JsonFormatter(logging.Formatter):
    """
    Formatter JSON (una línea por evento) para que sea fácil de parsear.
    """
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
            "service": os.getenv("APP_NAME", "spool-ctl-generator"),
            "host": socket.gethostname(),
        }

        # "extra" fields (los que pasas en logger.info(..., extra={...}))
        # Evita clonar todo el record; solo agrega campos “no estándar”.
        reserved = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
            "relativeCreated", "thread", "threadName", "processName", "process",
        }
        for k, v in record.__dict__.items():
            if k in reserved:
                continue
            if k.startswith("_"):
                continue
            if k not in base:
                base[k] = v

        if record.exc_info:
            base["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": "".join(traceback.format_exception(*record.exc_info))[:20000],
            }

        return json.dumps(base, ensure_ascii=False)

class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True

def setup_logging() -> None:
    """
    Logging a:
      - consola (dev)
      - archivo JSON rotativo (prod local)
    """
    level_str = (os.getenv("APP_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    log_dir = Path(os.getenv("APP_LOG_DIR") or (OUTPUT_FOLDER / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    json_path = log_dir / "app.jsonl"

    root = logging.getLogger()
    root.setLevel(level)

    # Limpia handlers previos (uvicorn reload, etc.)
    for h in list(root.handlers):
        root.removeHandler(h)

    # Consola (human-readable)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s rid=%(request_id)s - %(message)s"))
    ch.addFilter(RequestIdFilter())
    root.addHandler(ch)

    # Archivo JSON rotativo
    fh = RotatingFileHandler(
        filename=str(json_path),
        maxBytes=int(os.getenv("APP_LOG_MAX_BYTES") or 5_000_000),
        backupCount=int(os.getenv("APP_LOG_BACKUP_COUNT") or 10),
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(JsonFormatter())
    fh.addFilter(RequestIdFilter())
    root.addHandler(fh)

    # Reduce ruido de loggers comunes si lo deseas
    logging.getLogger("uvicorn.access").setLevel(os.getenv("UVICORN_ACCESS_LOG_LEVEL", "WARNING"))
    logging.getLogger("sqlalchemy.engine").setLevel(os.getenv("SQLALCHEMY_LOG_LEVEL", "WARNING"))


def new_request_id() -> str:
    return uuid.uuid4().hex
