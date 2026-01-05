# app/db/sql_sample.py
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from fastapi.encoders import jsonable_encoder
import re
import logging
import time

logger = logging.getLogger("app.sql")

def _mask_literals_and_comments(sql: str) -> str:
    """
    Devuelve una versión del SQL donde:
      - el contenido dentro de '...' y "..." se reemplaza por espacios
      - los comentarios -- ... y /* ... */ se reemplazan por espacios
    Mantiene los caracteres fuera de literales/comentarios intactos.
    Esto permite detectar ';' y keywords prohibidas fuera de strings/comentarios.
    """
    out = []
    i = 0
    n = len(sql)

    in_squote = False
    in_dquote = False
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        # Comentario de línea: -- hasta fin de línea
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            else:
                out.append(" ")
            i += 1
            continue

        # Comentario de bloque: /* ... */
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                out.append(" ")
                out.append(" ")
                i += 2
            else:
                out.append(" ")
                i += 1
            continue

        # Dentro de string literal '...'
        if in_squote:
            # Manejo de escape Oracle/MySQL: '' representa comilla simple
            if ch == "'" and nxt == "'":
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            if ch == "'":
                in_squote = False
                out.append(" ")
                i += 1
                continue
            out.append(" ")
            i += 1
            continue

        # Dentro de identificador "..."
        if in_dquote:
            # Manejo de escape: "" representa comilla doble
            if ch == '"' and nxt == '"':
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            if ch == '"':
                in_dquote = False
                out.append(" ")
                i += 1
                continue
            out.append(" ")
            i += 1
            continue

        # Entradas a comentarios
        if ch == "-" and nxt == "-":
            in_line_comment = True
            out.append(" ")
            out.append(" ")
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            out.append(" ")
            out.append(" ")
            i += 2
            continue

        # Entradas a literales
        if ch == "'":
            in_squote = True
            out.append(" ")
            i += 1
            continue
        if ch == '"':
            in_dquote = True
            out.append(" ")
            i += 1
            continue

        # Normal
        out.append(ch)
        i += 1

    return "".join(out)

def normalize_sql(sql: str) -> str:
    """
    Reglas:
      1) Solo se permite una sentencia (no ';' fuera de strings/comentarios)
      2) La sentencia debe iniciar con SELECT o WITH (ignorando espacios, comentarios y '(' iniciales)
      3) Se bloquean keywords típicas de DDL/DML/ejecución (BEGIN/EXEC/CALL, etc.)
      4) Se bloquea SELECT ... INTO OUTFILE/DUMPFILE (MySQL/MariaDB) por seguridad
    """
    s = (sql or "").strip()

    # Quitar ';' final (común al copiar desde editores)
    if s.endswith(";"):
        s = s[:-1].rstrip()

    if not s:
        raise ValueError("La consulta SQL está vacía.")

    masked = _mask_literals_and_comments(s)
    masked_lower = masked.lower()

    # 1) Bloquear múltiples sentencias: ';' fuera de literales/comentarios
    if ";" in masked:
        raise ValueError("No se permiten múltiples sentencias. Elimina ';' intermedios y deja una sola consulta.")

    # 2) Debe iniciar con SELECT o WITH (permitimos paréntesis iniciales)
    #    Ej: (SELECT ...) o WITH ... SELECT ...
    if not re.match(r"^\s*\(*\s*(select|with)\b", masked_lower):
        raise ValueError("Solo se permiten consultas de lectura: SELECT o WITH ... SELECT.")

    # 3) Bloqueo de keywords peligrosas fuera de strings/comentarios
    forbidden = re.compile(
        r"\b("
        r"insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
        r"commit|rollback|savepoint|"
        r"call|execute|exec|"
        r"begin|declare|"
        r"set|use"
        r")\b",
        re.IGNORECASE,
    )
    m = forbidden.search(masked)
    if m:
        raise ValueError(f"Consulta rechazada: contiene keyword no permitida '{m.group(0)}'.")

    # 4) Riesgo específico MariaDB/MySQL: SELECT ... INTO OUTFILE/DUMPFILE
    if re.search(r"\binto\s+(outfile|dumpfile)\b", masked_lower):
        raise ValueError("Consulta rechazada: no se permite SELECT ... INTO OUTFILE/DUMPFILE.")

    return s

def build_sample_sql(sql: str, dialect_name: str, limit: int = 100) -> str:
    """
    Genera un wrapper para obtener una muestra de filas, sin “adivinar” columnas por parsing.
    - Oracle: ROWNUM
    - Otros: LIMIT
    """
    dialect = (dialect_name or "").lower()

    if dialect in {"oracle", "oracledb", "cx_oracle"}:
        return f"SELECT * FROM (\n{sql}\n) q WHERE ROWNUM <= {int(limit)}"
    else:
        return f"SELECT * FROM (\n{sql}\n) q LIMIT {int(limit)}"

def fetch_columns_from_query(engine: Engine, sql: str, limit: int = 100) -> list[str]:
    start = time.perf_counter()
    try:
        sql = normalize_sql(sql)
        sample_sql = build_sample_sql(sql, engine.dialect.name, limit=limit)

        # Nota: ejecutamos la consulta (muestra) para que el driver nos devuelva metadata de columnas.
        with engine.connect() as conn:
            result = conn.execute(text(sample_sql))
            return list(result.keys())
    except Exception:
        logger.exception(
            "sql_exec_error",
            extra={
                "event": "sql_exec_error",
                "phase": "fetch_columns_from_query",
                "limit": limit,
                "sql_len": len(sql),
            },
        )
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "sql_exec_done",
            extra={
                "event": "sql_exec_done",
                "phase": "fetch_columns_from_query",
                "limit": limit,
                "sql_len": len(sql),
                "duration_ms": round(elapsed_ms, 2),
            },
        )

def fetch_preview_from_query(engine: Engine, sql: str, limit: int = 10) -> dict:
    """
    Ejecuta una muestra limitada y retorna:
      { "columns": [...], "rows": [[...], ...], "row_count": n }
    """
    start = time.perf_counter()
    try:
        sql = normalize_sql(sql)
        sample_sql = build_sample_sql(sql, engine.dialect.name, limit=limit)

        with engine.connect() as conn:
            result = conn.execute(text(sample_sql))
            cols = list(result.keys())
            rows = [list(r) for r in result.fetchmany(limit)]

        return jsonable_encoder({"columns": cols, "rows": rows, "row_count": len(rows)})
    except Exception:
        logger.exception(
            "sql_exec_error",
            extra={
                "event": "sql_exec_error",
                "phase": "fetch_columns_from_query",
                "limit": limit,
                "sql_len": len(sql),
            },
        )
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "sql_exec_done",
            extra={
                "event": "sql_exec_done",
                "phase": "fetch_columns_from_query",
                "limit": limit,
                "sql_len": len(sql),
                "duration_ms": round(elapsed_ms, 2),
            },
        )
