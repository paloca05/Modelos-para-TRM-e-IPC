# Pipeline de datos macroeconómicos – Proyecto ferretero

Extracción automática de TRM e IPC para el modelo de pronóstico de demanda ferretera.

## Estructura del proyecto

```
pipeline_macro/
├── .github/
│   └── workflows/
│       ├── pipeline_trm_diario.yml    ← se ejecuta lunes–viernes 8am COL
│       └── pipeline_ipc_mensual.yml   ← se ejecuta día 5 de cada mes
├── scripts/
│   ├── extraer_trm.py
│   └── extraer_ipc.py
├── data/                              ← generada automáticamente
│   ├── macro_colombia.csv             ← CSV maestro con todas las variables
│   └── pipeline_log.csv              ← auditoría de ejecuciones
└── requirements.txt
```

## Configuración inicial (una sola vez)

### 1. Crear el repositorio en GitHub

```bash
git init
git remote add origin https://github.com/TU_USUARIO/pipeline-macro-ferretero.git
git add .
git commit -m "feat: configuración inicial del pipeline"
git push -u origin main
```

### 2. Activar permisos de escritura para el workflow

En GitHub: **Settings → Actions → General → Workflow permissions**
Seleccionar: **"Read and write permissions"** → Guardar.

### 3. Descargar el histórico completo (una sola vez)

Ejecutar manualmente desde **Actions → Pipeline TRM diario → Run workflow**:
- `rango_inicio`: `2021-01-01`
- `rango_fin`: fecha de hoy

Para el IPC: **Actions → Pipeline IPC mensual → Run workflow**:
- `anio`: `2021`, luego `2022`, `2023`, `2024`, `2025` (una ejecución por año)

### 4. A partir de ahí, todo es automático

Los workflows se ejecutan solos según el cron configurado.

## Ejecutar localmente (para pruebas)

```bash
pip install -r requirements.txt

# TRM: descargar ayer
python scripts/extraer_trm.py

# TRM: rango histórico
python scripts/extraer_trm.py --rango 2021-01-01 2024-12-31

# IPC: mes más reciente
python scripts/extraer_ipc.py

# IPC: año completo
python scripts/extraer_ipc.py --anio 2023
```

## Formato del CSV maestro

```
fecha,trm,variable
2024-01-02,3950.21,trm
2024-01-03,3960.10,trm
...
2024-01-01,155.32,ipc
2024-02-01,156.41,ipc
```

La columna `variable` permite filtrar por indicador:

```python
import pandas as pd
df = pd.read_csv("data/macro_colombia.csv", parse_dates=["fecha"])
trm = df[df["variable"] == "trm"].set_index("fecha")["trm"]
ipc = df[df["variable"] == "ipc"].set_index("fecha")["ipc"]
```

## Fuentes oficiales

| Variable | Fuente | URL |
|----------|--------|-----|
| TRM diaria | Superfinanciera / datos.gov.co | https://www.datos.gov.co/resource/32sa-8pi3.json |
| IPC mensual | DANE / datos.gov.co | https://www.datos.gov.co/resource/j7dc-afuc.json |
| PIB Colombia | Banco Mundial | https://api.worldbank.org/v2/country/COL/indicator/NY.GDP.MKTP.CD |
