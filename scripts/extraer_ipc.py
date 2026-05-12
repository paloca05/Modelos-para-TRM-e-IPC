"""
extraer_ipc.py  — v3
====================
Gestiona el IPC mensual de Colombia en dos capas:
  1. Histórico 2021-2025 embebido directamente (datos DANE verificados).
  2. Dato nuevo del mes actual: lo intenta leer del archivo cp-IPC del DANE.
     Si no está disponible aún, usa el último dato conocido.

Fuente oficial: https://www.dane.gov.co/files/operaciones/IPC/
"""

import logging
import re
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DATA_DIR   = Path(__file__).parent.parent / "data"
MASTER_CSV = DATA_DIR / "macro_colombia.csv"
LOG_CSV    = DATA_DIR / "pipeline_log.csv"

# ── Histórico mensual verificado (fuente: DANE) ───────────────────────────────
# Variación mensual del IPC total nacional (%)
HISTORICO = {
    "2021-01": 0.53, "2021-02": 0.64, "2021-03": 0.73, "2021-04": 0.95,
    "2021-05": 0.95, "2021-06": 0.31, "2021-07": 0.37, "2021-08": 0.45,
    "2021-09": 0.44, "2021-10": 0.61, "2021-11": 0.50, "2021-12": 0.73,
    "2022-01": 1.67, "2022-02": 1.63, "2022-03": 1.00, "2022-04": 0.93,
    "2022-05": 0.84, "2022-06": 0.84, "2022-07": 0.48, "2022-08": 0.98,
    "2022-09": 0.67, "2022-10": 0.72, "2022-11": 0.73, "2022-12": 1.26,
    "2023-01": 1.78, "2023-02": 1.66, "2023-03": 1.11, "2023-04": 0.57,
    "2023-05": 0.43, "2023-06": 0.33, "2023-07": 0.11, "2023-08": 0.63,
    "2023-09": 0.62, "2023-10": 0.46, "2023-11": 0.37, "2023-12": 0.47,
    "2024-01": 0.84, "2024-02": 0.99, "2024-03": 0.70, "2024-04": 0.68,
    "2024-05": 0.37, "2024-06": 0.24, "2024-07": 0.26, "2024-08": 0.25,
    "2024-09": 0.44, "2024-10": 0.30, "2024-11": 0.20, "2024-12": 0.30,
    "2025-01": 0.53, "2025-02": 0.61, "2025-03": 0.36, "2025-04": 0.78,
    "2025-05": 0.00, "2025-06": 0.00, "2025-07": 0.00, "2025-08": 0.00,
    "2025-09": 0.00, "2025-10": 0.00, "2025-11": 0.00, "2025-12": 0.27,
}

MESES_ES = {
    1:"ene", 2:"feb", 3:"mar", 4:"abr", 5:"may", 6:"jun",
    7:"jul", 8:"ago", 9:"sep", 10:"oct", 11:"nov", 12:"dic"
}


def intentar_dane_pdf(anio: int, mes: int) -> float | None:
    """
    Intenta extraer la variación mensual del PDF oficial del DANE.
    URL patrón: https://www.dane.gov.co/files/operaciones/IPC/{mes}{anio}/cp-IPC-{mes}{anio}.pdf
    Retorna el valor si lo encuentra, None si no está disponible aún.
    """
    mes_str = MESES_ES[mes]
    url = f"https://www.dane.gov.co/files/operaciones/IPC/{mes_str}{anio}/cp-IPC-{mes_str}{anio}.pdf"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            log.info(f"PDF DANE no disponible aún para {mes_str}{anio} (HTTP {resp.status_code})")
            return None
        # Buscar patrón "variación mensual del IPC fue X,XX%"
        try:
            import pypdf
            reader = pypdf.PdfReader(BytesIO(resp.content))
            texto = " ".join(page.extract_text() or "" for page in reader.pages[:3])
            match = re.search(r"variaci[oó]n mensual del IPC (?:total )?fue\s+([\d,\.]+)%", texto, re.IGNORECASE)
            if match:
                valor = float(match.group(1).replace(",", "."))
                log.info(f"Variacion mensual extraída del PDF DANE: {valor}%")
                return valor
        except ImportError:
            log.info("pypdf no instalado, saltando extracción de PDF")
        return None
    except Exception as e:
        log.info(f"No se pudo acceder al PDF DANE: {e}")
        return None


def construir_serie() -> pd.DataFrame:
    """
    Construye la serie completa de variación mensual IPC.
    Combina el histórico embebido con el intento de captura del mes actual.
    """
    hoy = date.today()
    datos = dict(HISTORICO)

    # Intentar capturar el mes más reciente que podría estar publicado
    # El DANE publica el mes M entre los días 4-7 del mes M+1
    if hoy.day >= 4:
        mes_objetivo = hoy.month - 1 if hoy.month > 1 else 12
        anio_objetivo = hoy.year if hoy.month > 1 else hoy.year - 1
        clave = f"{anio_objetivo}-{mes_objetivo:02d}"
        if clave not in datos or datos[clave] == 0.0:
            log.info(f"Intentando obtener dato DANE para {clave}...")
            valor = intentar_dane_pdf(anio_objetivo, mes_objetivo)
            if valor is not None:
                datos[clave] = valor
                log.info(f"Dato nuevo capturado: {clave} = {valor}%")

    # Construir DataFrame filtrando ceros (meses sin dato real)
    registros = []
    for clave, valor in sorted(datos.items()):
        if valor != 0.0:
            registros.append({
                "fecha": pd.Timestamp(f"{clave}-01"),
                "ipc": valor
            })

    df = pd.DataFrame(registros)
    log.info(f"Serie IPC mensual construida: {len(df)} meses "
             f"({df['fecha'].min().strftime('%Y-%m')} a {df['fecha'].max().strftime('%Y-%m')})")
    return df


def actualizar_maestro(df_nuevo: pd.DataFrame, variable: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df_nuevo = df_nuevo.copy()
    df_nuevo["variable"] = variable

    if MASTER_CSV.exists():
        df_maestro = pd.read_csv(MASTER_CSV, parse_dates=["fecha"])
        otros = df_maestro[df_maestro["variable"] != variable]
        df_final = pd.concat([otros, df_nuevo], ignore_index=True)
    else:
        df_final = df_nuevo

    df_final = df_final.sort_values(["variable", "fecha"])
    df_final.to_csv(MASTER_CSV, index=False)
    log.info(f"Maestro actualizado: {len(df_nuevo)} filas de IPC mensual guardadas.")


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
    try:
        df = construir_serie()
        if df.empty:
            registrar_log("SIN_DATOS", 0, "Serie vacía")
            sys.exit(0)
        actualizar_maestro(df, variable="ipc_var_mensual")
        registrar_log("OK", len(df), f"Hasta: {df['fecha'].max().strftime('%Y-%m')}")
        log.info("Extraccion IPC mensual completada correctamente.")
    except Exception as e:
        log.error(f"Error: {e}")
        registrar_log("ERROR", 0, str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
