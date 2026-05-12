"""
extraer_ipc.py  — v2
====================
Descarga el IPC de Colombia desde la API del Banco Mundial.
Fuente: World Bank Open Data  |  Indicador: FP.CPI.TOTL (base 2010=100)
URL: https://api.worldbank.org/v2/country/COL/indicator/FP.CPI.TOTL

Sin autenticación. Sin API key. Actualización anual (enero de cada año).
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

WB_URL = "https://api.worldbank.org/v2/country/COL/indicator/FP.CPI.TOTL"
DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_CSV = DATA_DIR / "macro_colombia.csv"
LOG_CSV    = DATA_DIR / "pipeline_log.csv"


def fetch_ipc_worldbank() -> pd.DataFrame:
    params = {
        "format":   "json",
        "per_page": 100,
        "mrv":      30,   # últimos 30 años
    }
    log.info("Consultando IPC Colombia en World Bank API...")
    resp = requests.get(WB_URL, params=params, timeout=30)
    resp.raise_for_status()

    payload = resp.json()
    if len(payload) < 2 or not payload[1]:
        log.warning("La API del Banco Mundial no devolvió datos.")
        return pd.DataFrame()

    registros = [
        {"fecha": pd.Timestamp(f"{r['date']}-01-01"), "ipc": float(r["value"])}
        for r in payload[1]
        if r.get("value") is not None
    ]
    df = pd.DataFrame(registros).sort_values("fecha").reset_index(drop=True)
    log.info(f"IPC obtenido: {len(df)} registros ({df['fecha'].min().year}–{df['fecha'].max().year})")
    return df


def actualizar_maestro(df_nuevo: pd.DataFrame, variable: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df_nuevo = df_nuevo.copy()
    df_nuevo["variable"] = variable

    if MASTER_CSV.exists():
        df_maestro = pd.read_csv(MASTER_CSV, parse_dates=["fecha"])
        otros = df_maestro[df_maestro["variable"] != variable]
        fechas_nuevas = set(df_nuevo["fecha"])
        var_viejos = df_maestro[
            (df_maestro["variable"] == variable) &
            (~pd.to_datetime(df_maestro["fecha"]).isin(fechas_nuevas))
        ]
        df_final = pd.concat([otros, var_viejos, df_nuevo], ignore_index=True)
    else:
        df_final = df_nuevo

    df_final = df_final.sort_values(["variable", "fecha"])
    df_final.to_csv(MASTER_CSV, index=False)
    log.info(f"Maestro actualizado: {MASTER_CSV} ({len(df_final)} filas totales)")


def registrar_log(estado, filas, detalle=""):
    DATA_DIR.mkdir(exist_ok=True)
    reg = pd.DataFrame([{
        "timestamp": pd.Timestamp.now().isoformat(),
        "script": "extraer_ipc.py",
        "estado": estado,
        "filas_procesadas": filas,
        "detalle": detalle,
    }])
    if LOG_CSV.exists():
        reg.to_csv(LOG_CSV, mode="a", header=False, index=False)
    else:
        reg.to_csv(LOG_CSV, index=False)


def main():
    parser = argparse.ArgumentParser(description="Extrae IPC Colombia desde World Bank API")
    parser.add_argument("--anio", type=int, help="(ignorado — la API trae todo el histórico)")
    args = parser.parse_args()

    try:
        df = fetch_ipc_worldbank()
        if df.empty:
            registrar_log("SIN_DATOS", 0, "World Bank no devolvio datos")
            sys.exit(0)

        actualizar_maestro(df, variable="ipc")
        registrar_log("OK", len(df), f"Anios: {df['fecha'].min().year}-{df['fecha'].max().year}")
        log.info("Extraccion IPC completada correctamente.")

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
