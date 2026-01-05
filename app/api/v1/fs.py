# app/api/v1/fs.py
from __future__ import annotations

import os
import re
import string
from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, HTTPException, Query

from app.core.settings import (
    BASE_DOCS_DIR,
    _FORBIDDEN_EXPORT_CHARS,
    _UNC_ADMIN_SHARE,
)

router = APIRouter(prefix="/fs", tags=["fs"])


def _fs_norm_dir(p: str) -> str:
    s = (p or "").strip().replace("/", "\\") if os.name == "nt" else (p or "").strip()
    s = s.rstrip()
    if os.name == "nt" and s and not s.endswith("\\"):
        s += "\\"
    if os.name != "nt" and s and not s.endswith("/"):
        s += "/"
    return s

def _fs_has_traversal(p: str) -> bool:
    parts = (p or "").replace("/", "\\").split("\\") if os.name == "nt" else (p or "").split("/")
    return any(x == ".." for x in parts)

def _fs_is_abs_drive_or_unc(p: str) -> bool:
    if os.name != "nt":
        return (p or "").startswith("/")
    s = (p or "").strip()
    return bool(re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith("\\\\")

def _fs_default_deny_prefixes() -> list[str]:
    # Debe ser coherente con settings.py (puedes ajustar por env var igual que allá)
    return [
        r"C:\Windows\\",
        r"C:\Program Files\\",
        r"C:\Program Files (x86)\\",
        r"C:\ProgramData\\",
        r"C:\$Recycle.Bin\\",
        r"C:\System Volume Information\\",
    ]

def _fs_load_deny_prefixes() -> list[str]:
    raw = (os.getenv("SPOOL_DENY_PREFIXES") or "").strip()
    prefixes = [p.strip() for p in raw.split(";") if p.strip()] if raw else _fs_default_deny_prefixes()
    if os.name == "nt":
        return [_fs_norm_dir(x) for x in prefixes]
    return prefixes

def _fs_is_denied_by_prefix(path_abs: str) -> bool:
    if os.name != "nt":
        return False
    t = _fs_norm_dir(path_abs).lower()
    for pref in _fs_load_deny_prefixes():
        p = _fs_norm_dir(pref).lower()
        if t.startswith(p):
            return True
    return False

def _fs_parent(path_abs: str) -> str:
    if os.name != "nt":
        p = Path(path_abs.rstrip("/"))
        parent = str(p.parent) + "/"
        return parent if parent != "//" else "/"
    p = PureWindowsPath(path_abs.rstrip("\\"))
    parent = str(p.parent)
    # para C:\ -> parent se queda C:\ (evitamos loops raros)
    if re.match(r"^[A-Za-z]:$", parent):
        parent += "\\"
    return _fs_norm_dir(parent)

def _fs_list_dirs(path_abs: str) -> list[dict]:
    items = []
    with os.scandir(path_abs) as it:
        for e in it:
            if e.is_dir(follow_symlinks=False):
                child = _fs_norm_dir(e.path)
                denied = _fs_is_denied_by_prefix(child) or (os.name == "nt" and child.startswith("\\\\") and _UNC_ADMIN_SHARE.match(child))
                items.append({"name": e.name, "path": child, "denied": denied})
    items.sort(key=lambda x: x["name"].lower())
    return items

@router.get("/roots")
def fs_roots():
    if os.name != "nt":
        return [{"label": "/", "path": "/"}]

    roots = []
    # acceso rápido a Documents (tu base actual)
    docs = _fs_norm_dir(str(BASE_DOCS_DIR))
    roots.append({"label": "Documents", "path": docs})

    # drives disponibles
    for d in string.ascii_uppercase:
        candidate = f"{d}:\\"
        if os.path.exists(candidate):
            roots.append({"label": candidate, "path": candidate})
    return roots

@router.get("/list")
def fs_list(path: str):
    p = (path or "").strip()

    if not p:
        raise HTTPException(status_code=400, detail="path es requerido.")

    if _FORBIDDEN_EXPORT_CHARS.search(p):
        raise HTTPException(status_code=400, detail="Ruta inválida: contiene caracteres no permitidos.")
    if _fs_has_traversal(p):
        raise HTTPException(status_code=400, detail="Ruta inválida: no se permite '..'.")

    p = _fs_norm_dir(p)

    if not _fs_is_abs_drive_or_unc(p):
        raise HTTPException(status_code=400, detail="Ruta inválida: debe ser absoluta (drive, UNC o /).")

    # bloqueos (navegación) por denylist / admin shares
    if _fs_is_denied_by_prefix(p):
        raise HTTPException(status_code=403, detail="Acceso denegado: ruta restringida por política.")
    if os.name == "nt" and p.startswith("\\\\") and _UNC_ADMIN_SHARE.match(p):
        raise HTTPException(status_code=403, detail="Acceso denegado: shares administrativos no permitidos.")

    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Directorio no encontrado.")
    if not os.path.isdir(p):
        raise HTTPException(status_code=400, detail="La ruta no es un directorio.")

    try:
        folders = _fs_list_dirs(p)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Sin permisos para listar este directorio.")
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"No se pudo listar el directorio. {str(e)}")

    parent = _fs_parent(p)
    # Evita que el botón Arriba se vuelva infinito en raíz
    parent_same = (parent.lower() == p.lower()) if os.name == "nt" else (parent == p)

    return {
        "path": p,
        "parent": None if parent_same else parent,
        "folders": folders,
        "folder_count": len(folders),
    }
