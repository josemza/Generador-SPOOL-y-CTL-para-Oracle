# app/core/settings.py
from __future__ import annotations

from pathlib import Path, PureWindowsPath
import os
import re
import unicodedata

# Bloquea caracteres que rompen SPOOL o permiten comportamientos inesperados en SQL*Plus
_FORBIDDEN_EXPORT_CHARS = re.compile(r'["\'\r\n\t&;|<>]')

# Bloquea shares administrativos: \\server\C$\..., \\server\ADMIN$\...
_UNC_ADMIN_SHARE = re.compile(r"^\\\\[^\\]+\\([a-zA-Z]\$|admin\$)\\", re.IGNORECASE)

def _home_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")


def _default_docs_dir() -> Path:
    # En Windows normalmente existe Documents; en otros entornos, cae a HOME.
    home = _home_dir()
    docs = home / "Documents"
    return docs if docs.exists() else home


BASE_DOCS_DIR = Path(os.environ.get("APP_BASE_DOCS_DIR") or _default_docs_dir())

UPLOAD_FOLDER = Path(os.environ.get("APP_UPLOAD_DIR") or (BASE_DOCS_DIR / "uploads"))
OUTPUT_FOLDER = Path(os.environ.get("APP_OUTPUT_DIR") or (BASE_DOCS_DIR / "outputs"))

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

def _norm_dir(p: str) -> str:
    s = (p or "").strip().replace("/", "\\")
    # colapsa espacios finales que en Windows son problemáticos
    s = s.rstrip()
    if s and not s.endswith("\\"):
        s += "\\"
    return s

def _has_traversal(p: str) -> bool:
    parts = _norm_dir(p).split("\\")
    return any(part == ".." for part in parts)

def _is_abs_drive_or_unc(p: str) -> bool:
    s = (p or "").strip()
    return bool(re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith("\\\\")

def _default_deny_prefixes() -> list[str]:
    # Puedes ampliar/ajustar según políticas internas
    return [
        r"C:\Windows\\",
        r"C:\Program Files\\",
        r"C:\Program Files (x86)\\",
        r"C:\ProgramData\\",
        r"C:\$Recycle.Bin\\",
        r"C:\System Volume Information\\",
    ]

def _load_deny_prefixes() -> list[str]:
    # Permite configuración por env var (separado por ;)
    raw = (os.getenv("SPOOL_DENY_PREFIXES") or "").strip()
    if not raw:
        prefixes = _default_deny_prefixes()
    else:
        prefixes = [p.strip() for p in raw.split(";") if p.strip()]

    # Normaliza a backslash y asegura trailing "\"
    norm = []
    for p in prefixes:
        norm.append(_norm_dir(p))
    return norm

def _is_denied_by_prefix(path_abs: str) -> bool:
    target = str(PureWindowsPath(_norm_dir(path_abs)))
    t = target.lower()

    for pref in _load_deny_prefixes():
        p = str(PureWindowsPath(_norm_dir(pref))).lower()
        if t.startswith(p):
            return True
    return False

def _fs_validate_dir_writable(path_abs: str) -> None:
    """
    Validación opcional (habilitar con SPOOL_VALIDATE_EXPORT_PATH_FS=1):
    - existe y es directorio
    - el usuario puede escribir (prueba con archivo temporal)
    """
    import uuid

    p = Path(path_abs)
    if not p.exists():
        raise ValueError("La ruta no existe.")
    if not p.is_dir():
        raise ValueError("La ruta no es un directorio.")

    # Prueba de escritura: crea y borra un archivo temporal
    test_file = p / f".spool_path_test_{uuid.uuid4().hex}.tmp"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception:
        raise ValueError("No tienes permisos de escritura en la ruta seleccionada.")

def sanitize_filename_component(value: str, default: str = "archivo") -> str:
    """
    Sanitiza para usar en nombres de archivo (sin espacios raros, sin tildes,
    solo a-zA-Z0-9_-), y evita strings vacíos.
    """
    s = (value or "").strip()
    if not s:
        return default

    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")

    # Reemplaza espacios por guion bajo y remueve lo demás
    s = s.replace(" ", "_")
    s = re.sub(r"[^a-zA-Z0-9_\-]+", "", s)

    s = re.sub(r"_{2,}", "_", s).strip("_")
    return s or default

def normalize_export_path(p: str) -> str:
    """
    Hardening export_path:
    - Permite drive y UNC
    - Bloquea caracteres peligrosos para SQL*Plus (incluye '&')
    - Bloquea '..' (path traversal)
    - Bloquea shares admin (\\server\\C$\\, \\server\\ADMIN$\\)
    - Bloquea rutas del sistema por lista negra (prefijos)
    - Normaliza a backslash y asegura trailing '\\'
    """
    s = (p or "").strip()
    if not s:
        return s  # sigue siendo requerido por el formulario

    if _FORBIDDEN_EXPORT_CHARS.search(s):
        raise ValueError(
            "Ruta inválida: contiene caracteres no permitidos (comillas, saltos de línea, &, ;, etc.)."
        )

    if _has_traversal(s):
        raise ValueError("Ruta inválida: no se permite '..' en la ruta.")

    s = _norm_dir(s)

    if not _is_abs_drive_or_unc(s):
        # En tu caso (local por usuario) conviene exigir absoluto para evitar ambigüedad
        raise ValueError("Ruta inválida: debe ser absoluta (C:\\... o \\\\servidor\\share\\...).")

    # UNC admin shares: denegar
    if s.startswith("\\\\") and _UNC_ADMIN_SHARE.match(s):
        raise ValueError("Ruta inválida: no se permiten shares administrativos (C$, ADMIN$).")

    # Denylist por prefijo (Windows system dirs, etc.)
    if _is_denied_by_prefix(s):
        raise ValueError("Ruta inválida: no se permite exportar en rutas del sistema.")

    # Validación opcional de filesystem (recomendado en local)
    if os.getenv("SPOOL_VALIDATE_EXPORT_PATH_FS", "0") == "1":
        _fs_validate_dir_writable(s)

    return s