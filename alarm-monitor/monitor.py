#!/usr/bin/env python3
"""
Serviço de monitoramento de alarmes ENTEL.
Roda independente do dashboard Flet, dentro do Docker.
Lê configuração de /app/data (volume compartilhado), consulta
o InfluxDB e envia e-mail quando tensão sai dos limites.
"""
import os
import sys
import time
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Módulos compartilhados com o dashboard (montados via volume)
sys.path.insert(0, os.environ.get("DATA_DIR", "/app/data"))
import config_store
import auth

from influxdb_client import InfluxDBClient

# ── Variáveis de ambiente ─────────────────────────────────────────────────────
INFLUXDB_URL    = os.environ["INFLUXDB_URL"]
INFLUXDB_TOKEN  = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG    = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "telemetry")
SMTP_USER       = os.environ["SMTP_USER"]
SMTP_PASS       = os.environ["SMTP_PASS"]

POLL_INTERVAL  = 1.0   # segundos
EMAIL_COOLDOWN = 300   # segundos entre e-mails do mesmo evento ativo

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("alarm-monitor")

# ── Estado do alarme ──────────────────────────────────────────────────────────
alarme = {
    "ativo":        False,
    "fora_desde":   None,
    "dentro_desde": None,
    "ultimo_email": 0.0,
    "ultimo_tipo":  None,
}


# ── E-mail ────────────────────────────────────────────────────────────────────
def enviar_email(tipo: str, v: float, v_min: float, v_max: float) -> None:
    destinatarios = auth.get_notification_emails()
    if not destinatarios:
        log.warning("Nenhum e-mail de destino configurado — e-mail não enviado")
        return

    limite_str = f"mínimo: {v_min} V" if tipo == "SUBTENSÃO" else f"máximo: {v_max} V"
    agora_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    subject = f"🚨 [ENTEL] {tipo}: {v:.1f} V"
    body    = (
        f"Alerta de tensão detectado pelo sistema de monitoramento ENTEL.\n\n"
        f"Tipo        : {tipo}\n"
        f"Medição     : {v:.1f} V\n"
        f"Limite      : {limite_str}\n"
        f"Dispositivo : lorawan-entel (TTN)\n"
        f"Data/Hora   : {agora_str}\n\n"
        f"---\n"
        f"Sistema de Telemetria ENTEL\n"
        f"(mensagem automática — não responda)\n"
    )

    try:
        msg           = MIMEMultipart()
        msg["From"]   = SMTP_USER
        msg["To"]     = ", ".join(destinatarios)
        msg["Subject"]= subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as srv:
            srv.login(SMTP_USER, SMTP_PASS)
            srv.sendmail(SMTP_USER, destinatarios, msg.as_string())

        log.info(f"E-mail enviado → {destinatarios} | {tipo} {v:.1f} V")
        alarme["ultimo_email"] = time.time()
        alarme["ultimo_tipo"]  = tipo
    except Exception as exc:
        log.error(f"Falha ao enviar e-mail: {exc}")


# ── Lógica do alarme ──────────────────────────────────────────────────────────
def verificar_alarme(v: float) -> None:
    cfg     = config_store.load()
    agora   = time.time()
    v_min   = cfg["v_min"]
    v_max   = cfg["v_max"]
    hist    = cfg["histerese"]
    fora    = v < v_min or v > v_max
    na_hist = (v_min + v_min * hist / 100.0) <= v <= (v_max - v_max * hist / 100.0)

    if fora:
        alarme["dentro_desde"] = None
        if alarme["fora_desde"] is None:
            alarme["fora_desde"] = agora

        tempo_fora = agora - alarme["fora_desde"]
        tipo = "SUBTENSÃO" if v < v_min else "SOBRETENSÃO"

        if tempo_fora >= 1.0 and not alarme["ativo"]:
            # Nova ativação → e-mail imediato, sem cooldown
            alarme["ativo"]       = True
            alarme["ultimo_email"] = 0.0
            log.warning(f"{tipo}: {v:.1f} V (fora dos limites por {tempo_fora:.1f}s)")
            enviar_email(tipo, v, v_min, v_max)
        elif alarme["ativo"] and (agora - alarme["ultimo_email"]) >= EMAIL_COOLDOWN:
            # Lembrete periódico enquanto alarme permanece ativo
            log.warning(f"{tipo} continua: {v:.1f} V")
            enviar_email(tipo, v, v_min, v_max)
    else:
        alarme["fora_desde"] = None

        if not alarme["ativo"]:
            alarme["dentro_desde"] = None
            return

        if na_hist:
            if alarme["dentro_desde"] is None:
                alarme["dentro_desde"] = agora
            elif agora - alarme["dentro_desde"] >= 10.0:
                alarme["ativo"]        = False
                alarme["fora_desde"]   = None
                alarme["dentro_desde"] = None
                log.info("Tensão normalizada — alarme encerrado")
        else:
            alarme["dentro_desde"] = None


# ── InfluxDB ──────────────────────────────────────────────────────────────────
def buscar_tensao(query_api) -> float | None:
    flux = f'''
    from(bucket: "{INFLUXDB_BUCKET}")
      |> range(start: -2m)
      |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
      |> filter(fn: (r) => r["_field"] == "uplink_message_decoded_payload_tensao_v")
      |> last()
    '''
    try:
        for table in query_api.query(flux):
            for record in table.records:
                return float(record.get_value())
    except Exception as exc:
        log.debug(f"Erro ao consultar InfluxDB: {exc}")
    return None


# ── Loop principal ────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=== Monitor de alarmes ENTEL iniciado ===")
    log.info(f"InfluxDB : {INFLUXDB_URL}  bucket={INFLUXDB_BUCKET}")
    log.info(f"Remetente: {SMTP_USER}")

    client    = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    query_api = client.query_api()

    while True:
        try:
            v = buscar_tensao(query_api)
            if v is not None:
                verificar_alarme(v)
        except Exception as exc:
            log.error(f"Erro no loop principal: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
