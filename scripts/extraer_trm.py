"""
extraer_trm.py
==============
Extrae la TRM diaria desde datos.gov.co (Superfinanciera).
Endpoint Socrata: https://www.datos.gov.co/resource/32sa-8pi3.json

Uso:
    python extraer_trm.py                    # descarga ayer
    python extraer_trm.py --fecha 2024-03-15 # descarga fecha específica
    python extraer_trm.py --rango 2024-01-01 2024-12-31  # rango histórico
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

# ── configuración ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_CSV = DATA_DIR / "macro_colombia.csv"
LOG_CSV = DATA_DIR / "pipeline_log.csv"


# ── funciones principales ──────────────────────────────────────────────────────

def fetch_trm(fecha_inicio: str, fecha_fin: str) -> pd.DataFrame:
    """Consulta la API REST de datos.gov.co y retorna DataFrame con TRM."""
    params = {
        "$where": f"vigenciadesde >= '{fecha_inicio}' AND vigenciadesde <= '{fecha_fin}'",
        "$limit": 5000,
        "$order": "vigenciadesde ASC",
    }
    log.info(f"Consultando TRM desde {fecha_inicio} hasta {fecha_fin}...")
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    if not data:
        log.warning("La API no devolvió datos para el rango solicitado.")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["fecha"] = pd.to_datetime(df["vigenciadesde"]).dt.date
    df["trm"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df[["fecha", "trm"]].dropna()
    log.info(f"TRM obtenida: {len(df)} registros.")
    return df


def validar_trm(df: pd.DataFrame) -> pd.DataFrame:
    """Validaciones básicas de calidad sobre los datos de TRM."""
    if df.empty:
        return df

    # rango razonable: TRM entre $2.000 y $6.000 COP/USD
    fuera_rango = df[(df["trm"] < 2000) | (df["trm"] > 6000)]
    if not fuera_rango.empty:
        log.warning(f"Se encontraron {len(fuera_rango)} valores de TRM fuera del rango esperado (2000–6000).")
        log.warning(fuera_rango.to_string())

    # duplicados por fecha
    duplicados = df[df.duplicated(subset="fecha", keep=False)]
    if not duplicados.empty:
        log.warning(f"Fechas duplicadas en TRM: {duplicados['fecha'].tolist()}")
        df = df.drop_duplicates(subset="fecha", keep="last")

    return df


def actualizar_maestro(df_nuevo: pd.DataFrame, variable: str = "trm") -> None:
    """Agrega los nuevos datos al CSV maestro sin duplicar fechas."""
    DATA_DIR.mkdir(exist_ok=True)
    df_nuevo = df_nuevo.copy()
    df_nuevo["variable"] = variable

    if MASTER_CSV.exists():
        df_maestro = pd.read_csv(MASTER_CSV)
        df_maestro["fecha"] = pd.to_datetime(df_maestro["fecha"])
        df_nuevo["fecha"] = pd.to_datetime(df_nuevo["fecha"])
        # eliminar fechas que ya existían para esta variable (upsert)
        mask = df_maestro["variable"] != variable
        df_maestro_otros = df_maestro[mask].copy()
        df_maestro_var = df_maestro[~mask].copy()
        fechas_nuevas = set(df_nuevo["fecha"])
        df_maestro_var = df_maestro_var[
            ~df_maestro_var["fecha"].isin(fechas_nuevas)
        ]
        df_final = pd.concat([df_maestro_otros, df_maestro_var, df_nuevo], ignore_index=True)
    else:
        df_final = df_nuevo.copy()

    # convertir fecha a string antes de guardar para evitar el error de pandas
    df_final["fecha"] = pd.to_datetime(df_final["fecha"]).dt.strftime("%Y-%m-%d")
    df_final = df_final.sort_values(["variable", "fecha"]).reset_index(drop=True)
    df_final.to_csv(MASTER_CSV, index=False)
    log.info(f"Maestro actualizado: {MASTER_CSV} ({len(df_final)} filas totales)")


def registrar_log(estado: str, filas: int, detalle: str = "") -> None:
    """Escribe una línea en el log de auditoría del pipeline."""
    DATA_DIR.mkdir(exist_ok=True)
    registro = pd.DataFrame([{
        "timestamp": pd.Timestamp.now().isoformat(),
        "script": "extraer_trm.py",
        "estado": estado,
        "filas_procesadas": filas,
        "detalle": detalle,
    }])
    if LOG_CSV.exists():
        registro.to_csv(LOG_CSV, mode="a", header=False, index=False)
    else:
        registro.to_csv(LOG_CSV, index=False)


# ── punto de entrada ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extrae TRM de datos.gov.co")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fecha", help="Fecha específica (YYYY-MM-DD)")
    group.add_argument("--rango", nargs=2, metavar=("INICIO", "FIN"),
                       help="Rango de fechas (YYYY-MM-DD YYYY-MM-DD)")
    args = parser.parse_args()

    if args.fecha:
        inicio = fin = args.fecha
    elif args.rango:
        inicio, fin = args.rango
    else:
        # por defecto: ayer (día hábil anterior)
        ayer = date.today() - timedelta(days=1)
        inicio = fin = str(ayer)

    try:
        df = fetch_trm(inicio, fin)
        df = validar_trm(df)

        if df.empty:
            registrar_log("SIN_DATOS", 0, f"Sin datos para {inicio}–{fin}")
            log.warning("No se actualizó el maestro (sin datos).")
            sys.exit(0)

        actualizar_maestro(df, variable="trm")
        registrar_log("OK", len(df), f"Rango: {inicio} a {fin}")
        log.info("Extraccion TRM completada correctamente.")

    except requests.exceptions.RequestException as e:
        log.error(f"Error de red: {e}")
        registrar_log("ERROR_RED", 0, str(e))
        sys.exit(1)
    except Exception as e:
        log.error(f"Error inesperado: {e}")
        registrar_log("ERROR", 0, str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
