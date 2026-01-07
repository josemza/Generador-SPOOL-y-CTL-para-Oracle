from pathlib import Path
import zipfile
import pandas as pd
from datetime import datetime
import uuid
import unicodedata
import re
import logging

from app.core.observability import get_request_id
from app.core.settings import UPLOAD_FOLDER, OUTPUT_FOLDER, sanitize_filename_component

logger = logging.getLogger("app.generators")

def limpiar_texto_completo(texto):
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto_limpio = re.sub(r'[^a-zA-Z0-9\s]', '', texto)
    texto_limpio = texto_limpio.replace(" ", "_").upper()
    
    return texto_limpio

def _unique_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def build_unique_sql_filename(report_name: str) -> str:
    base = sanitize_filename_component(report_name,default="reporte").lower()
    stamp = _unique_stamp()
    rand = uuid.uuid4().hex[:8]
    return f"control_{base}_{stamp}_{rand}.sql"

def build_unique_ctl_filename(table_name: str) -> str:
    base = sanitize_filename_component(table_name, default="tabla").lower()
    stamp = _unique_stamp()
    rand = uuid.uuid4().hex[:8]
    return f"carga_{base}_{stamp}_{rand}.ctl"

def build_unique_create_sql_filename(table_name: str) -> str:
    base = sanitize_filename_component(table_name, default="tabla").lower()
    stamp = _unique_stamp()
    rand = uuid.uuid4().hex[:8]
    return f"create_{base}_{stamp}_{rand}.sql"

def build_unique_zip_filename(table_name: str) -> str:
    base = sanitize_filename_component(table_name, default="tabla").lower()
    stamp = _unique_stamp()
    rand = uuid.uuid4().hex[:8]
    return f"{base}_archivos_{stamp}_{rand}.zip"

def _quote_oracle_identifier(ident: str) -> str:
    ident = (ident or "").strip()
    ident = ident.replace('"', '""')
    return f'"{ident}"'

def generar_archivo_control(nombre_tabla, columnas, delimitador, nombre_archivo_datos):
    cols = ",\n".join(columnas)
    contenido_ctl = f"""
OPTIONS (SKIP = 1)
LOAD DATA
INFILE '{nombre_archivo_datos}'
REPLACE USING TRUNCATE
INTO TABLE {nombre_tabla}
FIELDS TERMINATED BY '{delimitador}' OPTIONALLY ENCLOSED BY '"'
TRAILING NULLCOLS
(
{cols}
)
"""
    ruta_ctl = UPLOAD_FOLDER / build_unique_ctl_filename(nombre_tabla)
    ruta_ctl.write_text(contenido_ctl.strip(), encoding="utf-8")
    return str(ruta_ctl)

def generar_script_sql(nombre_tabla, columnas, tipos_datos):
    columnas_sql = []
    for columna, tipo in zip(columnas, tipos_datos):
        t = (tipo or "").lower()
        if "int" in t:
            tipo_sql = "NUMBER"
        elif "float" in t or "double" in t:
            tipo_sql = "FLOAT"
        elif "datetime" in t:
            tipo_sql = "DATE"
        else:
            tipo_sql = "VARCHAR2(255)"
        columnas_sql.append(f"{columna} {tipo_sql}")

    script_sql = f"CREATE TABLE {nombre_tabla} (\n" + ",\n".join(columnas_sql) + "\n);"
    ruta_sql = UPLOAD_FOLDER / build_unique_create_sql_filename(nombre_tabla)
    ruta_sql.write_text(script_sql.strip(), encoding="utf-8")
    return str(ruta_sql)

def generar_spool(export_path, report_name, from_source, columns):
    
    pieces = []
    for col in columns:
        val = f"REPLACE(NVL(TO_CHAR(A.{col}), ''), '\"', '\"\"')"
        pieces.append(f"'\"'||{val}||'\"'")

    # Une columnas con coma
    select_clause = "||','||\n".join(pieces)

    # Header con columnas (sin comillas)
    header = ",".join([_quote_oracle_identifier(str(c)) for c in columns])

    report_name = limpiar_texto_completo(report_name).lower()

    rid = get_request_id()
    generated_at = datetime.now().isoformat(timespec="seconds")

    control_file_content = f"""
-- generated_by=spool-ctl-generator
-- request_id={rid}
-- generated_at={generated_at}

SET LINESIZE 10000
SET ECHO OFF
SET TIMING OFF
SET PAGESIZE 0
SET TERMOUT OFF
SET FEEDBACK OFF
SET TRIMSPOOL ON

WHENEVER SQLERROR EXIT 1;

COLUMN tm NEW_VALUE FILE_TIME NOPRINT
SELECT to_char(TRUNC(SYSDATE - 1), 'DDMMYYYY') tm FROM DUAL;
PROMPT &FILE_TIME

SPOOL "{export_path}{report_name}_&FILE_TIME..csv"
SELECT '{header}' FROM DUAL;
SELECT
{select_clause}
FROM {from_source} A;

SPOOL OFF;
DISCONNECT;
EXIT;
""".strip()
    output_path = OUTPUT_FOLDER / build_unique_sql_filename(report_name)
    output_path.write_text(control_file_content, encoding="utf-8")

    try:
        size_bytes = output_path.stat().st_size
    except Exception:
        size_bytes = None

    logger.info(
        "artifact_written",
        extra={
            "event": "artifact_written",
            "artifact_type": "spool_sql",
            "path": str(output_path),
            "size_bytes": size_bytes,
            "report_name": report_name,
        },
    )

    return str(output_path)

def read_sample_columns(sample_path: Path) -> list[str]:
    # Lee la cabecera como haces hoy (primera línea CSV)
    first_line = sample_path.read_text(encoding="latin-1").splitlines()[0]
    return [c.strip() for c in first_line.split(",")]

def load_dataframe_from_upload(archivo):
    name = (archivo.filename or "").lower()
    content = archivo.file.read()

    if name.endswith(".csv"):
        # Replica tu comportamiento (latin-1)
        from io import BytesIO
        return pd.read_csv(BytesIO(content), encoding="latin-1")
    elif name.endswith(".xlsx"):
        from io import BytesIO
        return pd.read_excel(BytesIO(content))
    else:
        raise ValueError("Formato no soportado. Usa CSV o XLSX.")

def build_zip(zip_path: Path, files: list[Path]):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in files:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                path, arcname = item
                zf.write(str(path), arcname=str(arcname))
            else:
                path = item
                zf.write(str(path), arcname=Path(path).name)
