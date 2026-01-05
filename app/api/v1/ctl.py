# app/api/v1/ctl.py
from pathlib import Path
import pandas as pd

import logging
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.settings import sanitize_filename_component, OUTPUT_FOLDER

from app.services.generators import (
    generar_archivo_control,
    generar_script_sql,
    build_zip,
    build_unique_zip_filename,
)

logger = logging.getLogger("app.api.v1.ctl")

router = APIRouter(tags=["ctl"])


def load_dataframe_from_upload(file: UploadFile) -> pd.DataFrame:
    """
    Carga CSV o Excel a DataFrame de manera simple.
    Ajusta si en tu entorno solo usas CSV.
    """
    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        return pd.read_excel(file.file)
    # default CSV
    return pd.read_csv(file.file, encoding="latin-1")

@router.post("/ctl")
def generar_ctl_endpoint(
    archivo: UploadFile = File(...),
    nombre_tabla: str = Form(...),
    delimitador: str = Form(...),
):
    df = load_dataframe_from_upload(archivo)

    columnas = list(df.columns)
    tipos_datos = [str(dtype) for dtype in df.dtypes]

    ruta_ctl = Path(generar_archivo_control(nombre_tabla, columnas, delimitador, archivo.filename))
    ruta_sql = Path(generar_script_sql(nombre_tabla, columnas, tipos_datos))

    zip_path = OUTPUT_FOLDER / build_unique_zip_filename(nombre_tabla)

    safe_table = sanitize_filename_component(nombre_tabla, default="TABLA").upper()
    build_zip(
        zip_path,
        [
            (ruta_ctl, "carga.ctl"),
            (ruta_sql, f"{safe_table}.sql"),
        ],
    )

    def cleanup():
        try:
            ruta_ctl.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            ruta_sql.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass

    return FileResponse(
        path=str(zip_path),
        filename=zip_path.name,
        media_type="application/zip",
        background=BackgroundTask(cleanup),
    )
