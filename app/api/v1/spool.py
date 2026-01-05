# app/api/v1/spool.py
import csv
import tempfile
from pathlib import Path
from typing import Optional

import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from starlette.background import BackgroundTask
from sqlalchemy.exc import SQLAlchemyError

from app.core.settings import UPLOAD_FOLDER, normalize_export_path, sanitize_filename_component
from app.db.engine import get_engine
from app.db.sql_sample import normalize_sql, fetch_columns_from_query, fetch_preview_from_query
from app.services.generators import generar_spool

logger = logging.getLogger("app.api.v1.spool")

router = APIRouter(tags=["spool"])


def read_sample_columns(path: Path) -> list[str]:
    """
    Lee cabecera (primera línea) como columnas separadas por coma.
    """
    lines = path.read_text(encoding="latin-1", errors="replace").splitlines()
    if not lines:
        return []
    first = lines[0]
    cols = [c.strip() for c in first.split(",")]
    return [c for c in cols if c]

@router.post("/spool")
def spool_endpoint(
    source_mode: str = Form("csv"),  # "csv" | "sql"
    file: Optional[UploadFile] = File(None),
    table_name: Optional[str] = Form(None),
    sql_query: Optional[str] = Form(None),
    export_path: str = Form(...),
    report_name: str = Form(...),
):
    source_mode = (source_mode or "csv").strip().lower()

    logger.info(
        "spool_requested",
        extra={
            "event": "spool_requested",
            "source_mode": source_mode,
            "report_name": report_name,
            "export_path_raw": export_path,
            "table_name": table_name,
            "sql_len": len(sql_query or "") if source_mode == "sql" else None,
            "upload_filename": (file.filename if file else None),
        },
    )

    tmp_path: Optional[Path] = None
    output_path: Optional[Path] = None

    try:
        if source_mode == "csv":
            if file is None or not (file.filename or "").strip():
                raise HTTPException(status_code=400, detail="Selecciona un archivo CSV/TXT de muestra.")
            if not (table_name or "").strip():
                raise HTTPException(status_code=400, detail="Ingresa el nombre de tabla o cláusula FROM.")

            suffix = Path(file.filename).suffix.lower()
            if suffix not in [".csv", ".txt"]:
                raise HTTPException(status_code=400, detail="Sube un CSV (o TXT) para leer cabeceras.")

            with tempfile.NamedTemporaryFile(delete=False, dir=UPLOAD_FOLDER, suffix=suffix) as tmp:
                tmp.write(file.file.read())
                tmp_path = Path(tmp.name)
            
            try:
                sample_size = tmp_path.stat().st_size if tmp_path else None
            except Exception:
                sample_size = None

            logger.info(
                "sample_saved",
                extra={
                    "event": "sample_saved",
                    "sample_tmp_path": str(tmp_path) if tmp_path else None,
                    "sample_size_bytes": sample_size,
                },
            )

            columns = read_sample_columns(tmp_path)
            if not columns:
                raise HTTPException(status_code=400, detail="No se detectaron columnas en la cabecera del archivo.")

            from_source = table_name.strip()

        elif source_mode == "sql":
            try:
                q = normalize_sql(sql_query or "")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            try:
                engine = get_engine()
                columns = fetch_columns_from_query(engine, q, limit=100)
            except SQLAlchemyError as e:
                logger.exception(
                    "sqlalchemy_error_fetch_columns",
                    extra={
                        "event": "sqlalchemy_error",
                        "phase": "fetch_columns_from_query",
                        "sql_len": len(q),
                    },
                )
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No se pudo ejecutar la consulta para obtener una muestra (100 filas). "
                        f"Revisa tu SQL. Detalle: {str(e).splitlines()[0]}"
                    ),
                )

            # Inline view para soportar joins complejos
            from_source = f"(\n{q}\n)"

        else:
            raise HTTPException(status_code=400, detail="source_mode inválido. Usa 'csv' o 'sql'.")

        try:
            export_path = normalize_export_path(export_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        output_path = Path(generar_spool(export_path, report_name, from_source, columns))

        try:
            out_size = output_path.stat().st_size if output_path else None
        except Exception:
            out_size = None

        logger.info(
            "spool_generated",
            extra={
                "event": "spool_generated",
                "output_file": str(output_path) if output_path else None,
                "output_size_bytes": out_size,
                "columns_count": len(columns) if columns else 0,
                "from_source_kind": "inline_view" if (source_mode == "sql") else "table_or_from",
            },
        )

        def cleanup():
            try:
                if tmp_path:
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                if output_path:
                    output_path.unlink(missing_ok=True)
            except Exception:
                pass

        return FileResponse(
            path=str(output_path),
            filename=output_path.name,
            media_type="application/sql",
            background=BackgroundTask(cleanup),
        )

    except HTTPException:
        raise
    except Exception as e:
        # fallback controlado para que el front vea JSON y no un 500 genérico
        raise HTTPException(status_code=500, detail=f"Error interno al generar spool. {str(e)}")

@router.post("/spool/preview")
def spool_preview(
    source_mode: str = Form("csv"),
    file: Optional[UploadFile] = File(None),
    table_name: Optional[str] = Form(None),  # se mantiene por compatibilidad, aunque no se usa aquí
    sql_query: Optional[str] = Form(None),
    preview_rows: int = Form(10),
):
    source_mode = (source_mode or "csv").strip().lower()
    preview_rows = max(1, min(int(preview_rows or 10), 100))

    tmp_path: Optional[Path] = None

    try:
        if source_mode == "csv":
            if file is None or not (file.filename or "").strip():
                raise HTTPException(status_code=400, detail="Selecciona un archivo CSV/TXT para preview.")

            suffix = Path(file.filename).suffix.lower()
            if suffix not in [".csv", ".txt"]:
                raise HTTPException(status_code=400, detail="Formato no soportado para preview. Usa CSV o TXT.")

            with tempfile.NamedTemporaryFile(delete=False, dir=UPLOAD_FOLDER, suffix=suffix) as tmp:
                tmp.write(file.file.read())
                tmp_path = Path(tmp.name)

            text_content = tmp_path.read_text(encoding="latin-1", errors="replace").splitlines()
            if not text_content:
                raise HTTPException(status_code=400, detail="El archivo está vacío.")

            reader = csv.reader(text_content)
            columns = [c.strip() for c in (next(reader, []) or [])]

            rows = []
            for i, row in enumerate(reader):
                if i >= preview_rows:
                    break
                rows.append(list(row))

            return JSONResponse(
                content=jsonable_encoder(
                    {"mode": "csv", "columns": columns, "rows": rows, "row_count": len(rows)}
                )
            )

        elif source_mode == "sql":
            try:
                q = normalize_sql(sql_query or "")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            try:
                engine = get_engine()
                payload = fetch_preview_from_query(engine, q, limit=preview_rows)
            except SQLAlchemyError as e:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No se pudo ejecutar la consulta para preview. "
                        f"Revisa tu SQL. Detalle: {str(e).splitlines()[0]}"
                    ),
                )

            payload["mode"] = "sql"
            return JSONResponse(content=payload)

        else:
            raise HTTPException(status_code=400, detail="source_mode inválido. Usa 'csv' o 'sql'.")

    finally:
        try:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
