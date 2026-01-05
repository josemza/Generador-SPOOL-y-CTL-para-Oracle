# Generador de Spool (SQL*Plus) y CTL (SQL*Loader)

Aplicación web local para generar artefactos Oracle a partir de:
- Un **archivo de muestra** (CSV/TXT/Excel), o
- Una **consulta SQL** (solo lectura)

Incluye un frontend en **HTML/CSS/JS (vanilla)** servido por FastAPI.

---

## Qué resuelve

### 1) Generación de Spool (`.sql` para SQL\*Plus)
Genera un script `.sql` listo para ejecutar en SQL\*Plus que:
- Exporta a **CSV** con `SPOOL`
- Emite **header** con nombres de columnas
- Escapa comillas dobles dentro de valores y envuelve cada campo entre comillas (estilo CSV)  
  (ver `REPLACE(..., '"', '""')` en el generador)

El script se construye a partir de:
- **Modo CSV:** lee la cabecera del archivo de muestra para obtener columnas
- **Modo SQL:** ejecuta una muestra limitada (por defecto 100 filas) para obtener metadata de columnas (`result.keys()`)

### 2) Generación de CTL (`.ctl`) + SQL de creación
A partir de un archivo (CSV o Excel) se genera:
- `carga.ctl` (SQL\*Loader)
- `TABLA.sql` (script de `CREATE TABLE` básico según tipos inferidos)
- Un **ZIP** con ambos archivos

### 3) Vista previa (Preview)
- Preview de CSV/TXT: muestra columnas y primeras filas
- Preview de SQL: ejecuta una muestra limitada y retorna columnas + filas

### 4) Selección asistida de carpetas (local)
Endpoints utilitarios para listar carpetas del equipo (pensado para ejecución local por usuario):
- Roots (Documents + discos en Windows)
- Listado de subcarpetas

Incluye validaciones y bloqueos por seguridad (denylist de rutas del sistema y bloqueo de shares administrativos).

---

## Arquitectura (carpetas)

Estructura esperada (referencial):

```
.
├─ .env                          # NO se versiona
├─ arquitectura.txt
└─ app
   ├─ main.py                    # FastAPI + middleware + templates/static
   ├─ api
   │  └─ v1
   │     ├─ router.py            # include_router para v1
   │     ├─ spool.py             # endpoints spool + preview
   │     ├─ ctl.py               # endpoint ctl (zip)
   │     └─ fs.py                # endpoints filesystem helper
   ├─ core
   │  ├─ settings.py             # paths, sanitización y validaciones
   │  └─ observability.py        # logging JSON + request_id
   ├─ db
   │  ├─ engine.py               # get_engine (externo o DB_URL)
   │  └─ sql_sample.py           # validación SQL (solo lectura) + sample wrapper
   ├─ services
   │  └─ generators.py           # generadores spool/ctl/zip
   ├─ templates
   │  └─ index.html              # UI
   └─ static
      ├─ app.js                  # UI logic (vanilla)
      └─ styles.css
```

---

## Requisitos

- Python 3.10+ (recomendado 3.11+)
- Paquetes Python (ver `requirements.txt`)
- Si usarás modo SQL:
  - Driver/URL SQLAlchemy compatible (`DB_URL`) o tu módulo corporativo `conexion.conexion.get_engine()`

---

## Configuración por variables de entorno

Crea un archivo `.env` en la raíz (no lo subas a GitHub):

### Base
- `DB_URL`  
  URL SQLAlchemy (si no existe `conexion.conexion.get_engine()`).

Ejemplos:
- SQLite: `DB_URL=sqlite:///./local.db`
- MariaDB/MySQL: `DB_URL=mariadb+pymysql://user:pass@host:3306/db`
- Postgres: `DB_URL=postgresql+psycopg://user:pass@host:5432/db`

### Paths (por defecto usa *Documents* del usuario)
- `APP_BASE_DOCS_DIR`  
- `APP_UPLOAD_DIR`  
- `APP_OUTPUT_DIR`

Por defecto:
- Uploads: `Documents/uploads`
- Outputs: `Documents/outputs`

### Logs / Observabilidad
- `APP_LOG_LEVEL` (default: `INFO`)
- `APP_LOG_DIR` (default: `Documents/outputs/logs`)
- `APP_LOG_MAX_BYTES` (default: `5000000`)
- `APP_LOG_BACKUP_COUNT` (default: `10`)
- `UVICORN_ACCESS_LOG_LEVEL` (default: `WARNING`)
- `SQLALCHEMY_LOG_LEVEL` (default: `WARNING`)

### Seguridad (filesystem export path)
- `SPOOL_DENY_PREFIXES`  
  Lista `;` separada de prefijos denegados (Windows). Si no se define, usa una denylist por defecto.
- `SPOOL_VALIDATE_EXPORT_PATH_FS=1`  
  Activa validación real de filesystem (existencia y prueba de escritura) para la ruta de exportación.

---

## Ejecutar en local

### 1) Crear entorno virtual
Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/Mac:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2) Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3) Levantar servidor

Desde la raíz del repo:

```bash
uvicorn app.main:app --reload
```

Abrir en navegador:
- `http://127.0.0.1:8000/`

---

## API (v1)

La API está versionada bajo `/api/v1`.

### Spool
**POST** `/api/v1/spool` (form-data)

Campos:
- `source_mode`: `csv` | `sql`
- `file`: CSV/TXT (solo en modo `csv`)
- `table_name`: nombre de tabla o cláusula `FROM` (solo modo `csv`)
- `sql_query`: consulta (solo modo `sql`)
- `export_path`: ruta absoluta donde SQL\*Plus generará el CSV (se normaliza y valida)
- `report_name`: nombre lógico del reporte (se sanitiza para nombre de archivo)

Respuesta: descarga de archivo `.sql`.

### Preview
**POST** `/api/v1/spool/preview` (form-data)

Campos:
- `source_mode`: `csv` | `sql`
- `file` / `sql_query`
- `preview_rows` (1–100; default 10)

Respuesta JSON:
- `columns`, `rows`, `row_count`

### CTL
**POST** `/api/v1/ctl` (multipart)

Campos:
- `archivo`: CSV o Excel
- `nombre_tabla`
- `delimitador`

Respuesta: descarga de `.zip` con `carga.ctl` y `TABLA.sql`.

### Filesystem helper (UI local)
- **GET** `/api/v1/fs/roots`
- **GET** `/api/v1/fs/list?path=...`

---

## Seguridad básica (modo SQL)

El backend valida el SQL para permitir **solo lectura**:
- Solo se permite una sentencia (bloquea `;` intermedios)
- Debe iniciar con `SELECT` o `WITH`
- Bloquea keywords DDL/DML/ejecución (insert/update/delete/drop/alter/create/exec/begin, etc.)
- Bloquea `SELECT ... INTO OUTFILE/DUMPFILE`

Nota: estas validaciones son un hardening razonable para un entorno local, pero no sustituyen políticas de seguridad corporativas ni control de permisos en la base de datos.

---

## Notas de desarrollo

- El server añade `X-Request-ID` a cada respuesta y registra logs estructurados (JSONL) para trazabilidad.
- El frontend vive en `app/templates/index.html` + `app/static/*` y consume `/api/v1/*`.

---

## Roadmap sugerido

- Exportación “run-ready”: generar también `.bat` ejemplo para ejecutar SQL\*Plus/SQL\*Loader
- Plantillas de spool por tipo de export (separador, encoding, NULL handling)
- Validación avanzada de nombres de columnas (quoted identifiers, espacios, etc.)
- Tests (unitarios para `normalize_sql`, `normalize_export_path`, generadores)

