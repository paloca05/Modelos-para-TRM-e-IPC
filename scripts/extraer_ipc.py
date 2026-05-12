"""
extraer_ipc.py
==============
Extrae el IPC mensual del DANE desde datos.gov.co.
Se ejecuta una vez al mes (día 5) cuando el DANE publica el dato del mes anterior.

Uso:
    python extraer_ipc.py                    # descarga el mes más reciente
    python extraer_ipc.py --anio 2024        # descarga todo el año 2024
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

# Dataset IPC nacional total – datos.gov.co
# Documentación: https://www.datos.gov.co/resource/j7dc-afuc.json
IPC_URL = "https://www.datos.gov.co/resource/j7dc-afuc.json"

DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_CSV = DATA_DIR / "macro_colombia.csv"
LOG_CSV = DATA_DIR / "pipeline_log.csv"

# Columnas conocidas del dataset IPC del DANE en datos.gov.co
# (pueden variar si el DANE actualiza el dataset — verificar periódicamente)
COL_FECHA = "mes"          # formato: "2024-01" o "2024-01-01"
COL_VALOR = "ipc"          # índice base 2018=100
COL_VAR_MES = "variacion_mensual"
COL_VAR_ANUAL = "variacion_anual"


def fetch_ipc(anio: int = None) -> pd.DataFrame:
    """
    Descarga IPC desde datos.gov.co.
    Si anio es None, trae los últimos 24 meses.
    """
    params = {"$limit": 500, "$order": f"{COL_FECHA} ASC"}

    if anio:
        params["$where"] = f"mes >= '{anio}-01-01' AND mes <= '{anio}-12-31'"

    log.info(f"Consultando IPC {'año ' + str(anio) if anio else '(últimos 24 meses)'}...")
    response = requests.get(IPC_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    if not data:
        log.warning("La API no devolvió datos de IPC.")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    log.info(f"Columnas recibidas: {list(df.columns)}")

    # normalizar fecha a primer día del mes
    df["fecha"] = pd.to_datetime(df[COL_FECHA], errors="coerce").dt.to_period("M").dt.to_timestamp()
    df["ipc"] = pd.to_numeric(df.get(COL_VALOR), errors="coerce")

    # incluir variaciones si están disponibles
    cols_salida = ["fecha", "ipc"]
    if COL_VAR_MES in df.columns:
        df["ipc_var_mensual"] = pd.to_numeric(df[COL_VAR_MES], errors="coerce")
        cols_salida.append("ipc_var_mensual")
    if COL_VAR_ANUAL in df.columns:
        df["ipc_var_anual"] = pd.to_numeric(df[COL_VAR_ANUAL], errors="coerce")
        cols_salida.append("ipc_var_anual")

    df = df[cols_salida].dropna(subset=["fecha", "ipc"])
    log.info(f"IPC obtenido: {len(df)} registros.")
    return df


def validar_ipc(df: pd.DataFrame) -> pd.DataFrame:
    """Validaciones de calidad para el IPC."""
    if df.empty:
        return df

    # El índice IPC base 2018=100 debería estar entre 80 y 200 para el período relevante
    fuera_rango = df[(df["ipc"] < 80) | (df["ipc"] > 250)]
    if not fuera_rango.empty:
        log.warning(f"Valores de IPC fuera del rango esperado: {fuera_rango[['fecha', 'ipc']].to_string()}")

    # Variaciones mensuales no deberían superar ±5% (alertar si superan)
    if "ipc_var_mensual" in df.columns:
        extremos = df[df["ipc_var_mensual"].abs() > 5]
        if not extremos.empty:
            log.warning(f"Variaciones mensuales extremas detectadas: {extremos[['fecha', 'ipc_var_mensual']].to_string()}")

    duplicados = df[df.duplicated(subset="fecha")]
    if not duplicados.empty:
        log.warning(f"Meses duplicados en IPC: {duplicados['fecha'].tolist()}")
        df = df.drop_duplicates(subset="fecha", keep="last")

    return df


def actualizar_maestro(df_nuevo: pd.DataFrame, variable: str) -> None:
    """Upsert al CSV maestro para la variable dada."""
    DATA_DIR.mkdir(exist_ok=True)
    df_nuevo = df_nuevo.copy()
    df_nuevo["variable"] = variable

    if MASTER_CSV.exists():
        df_maestro = pd.read_csv(MASTER_CSV, parse_dates=["fecha"])
        mask = df_maestro["variable"] != variable
        df_otros = df_maestro[mask]
        df_var = df_maestro[~mask]
        fechas_nuevas = set(df_nuevo["fecha"])
        df_var = df_var[~pd.to_datetime(df_var["fecha"]).isin(fechas_nuevas)]
        df_final = pd.concat([df_otros, df_var, df_nuevo], ignore_index=True)
    else:
        df_final = df_nuevo

    df_final = df_final.sort_values(["variable", "fecha"])
    df_final.to_csv(MASTER_CSV, index=False)
    log.info(f"Maestro actualizado con IPC: {len(df_nuevo)} filas nuevas.")


def registrar_log(estado: str, filas: int, detalle: str = "") -> None:
    DATA_DIR.mkdir(exist_ok=True)
    registro = pd.DataFrame([{
        "timestamp": pd.Timestamp.now().isoformat(),
        "script": "extraer_ipc.py",
        "estado": estado,
        "filas_procesadas": filas,
        "detalle": detalle,
    }])
    if LOG_CSV.exists():
        registro.to_csv(LOG_CSV, mode="a", header=False, index=False)
    else:
        registro.to_csv(LOG_CSV, index=False)


def main():
    parser = argparse.ArgumentParser(description="Extrae IPC mensual del DANE")
    parser.add_argument("--anio", type=int, help="Año específico a descargar (ej: 2024)")
    args = parser.parse_args()

    try:
        df = fetch_ipc(anio=args.anio)
        df = validar_ipc(df)

        if df.empty:
            registrar_log("SIN_DATOS", 0, "Sin datos de IPC disponibles")
            sys.exit(0)

        # guardar IPC general
        actualizar_maestro(df[["fecha", "ipc", "variable"] if "variable" in df.columns
                               else ["fecha", "ipc"]], variable="ipc")

        # si hay variaciones, guardarlas como variables adicionales
        if "ipc_var_mensual" in df.columns:
            df_var = df[["fecha", "ipc_var_mensual"]].rename(columns={"ipc_var_mensual": "ipc"})
            actualizar_maestro(df_var, variable="ipc_var_mensual")

        registrar_log("OK", len(df), f"Anio: {args.anio or 'reciente'}")
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
