#!/usr/bin/env python3
"""
Simula o pipeline TTN -> Telegraf -> InfluxDB gravando diretamente na
measurement 'mqtt_consumer' com os mesmos nomes de campo que o Telegraf
produziria a partir do formatter TTN.

Usage:
  python simulate_data.py            # roda continuamente, intervalo padrão 5s
  python simulate_data.py 3          # intervalo de 3s
  python simulate_data.py --once     # envia um único ponto e sai
"""

import argparse
import math
import random
import time
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUXDB_URL    = "http://localhost:8086"
INFLUXDB_TOKEN  = "entel-2026"
INFLUXDB_ORG    = "entel"
INFLUXDB_BUCKET = "telemetry"

_energy_kwh = 0.0
_last_tick  = time.time()


def _sine_noise(base: float, amplitude: float, period_s: float, noise: float) -> float:
    t = time.time()
    return base + amplitude * math.sin(2 * math.pi * t / period_s) + random.uniform(-noise, noise)


def generate_data() -> dict:
    global _energy_kwh, _last_tick

    tensao_v   = round(_sine_noise(220.0, 3.0, 120, 0.5), 1)
    corrente_a = round(max(0.0, _sine_noise(1.5, 0.8, 180, 0.1)), 3)
    fp         = round(min(1.0, max(0.5, _sine_noise(0.92, 0.05, 300, 0.01))), 3)
    freq_hz    = round(_sine_noise(60.0, 0.05, 60, 0.02), 1)
    potencia_w = round(tensao_v * corrente_a * fp, 1)

    now = time.time()
    dt_h = (now - _last_tick) / 3600.0
    _last_tick = now
    _energy_kwh += potencia_w * dt_h / 1000.0  # W × h / 1000 = kWh

    return {
        "tensao_v":   tensao_v,
        "corrente_a": corrente_a,
        "potencia_w": potencia_w,
        "energia_kwh": round(_energy_kwh, 6),
        "freq_hz":    freq_hz,
        "fp":         fp,
    }


def build_point(data: dict) -> Point:
    p = Point("mqtt_consumer").time(datetime.now(timezone.utc), "s")
    for key, value in data.items():
        p = p.field(f"uplink_message_decoded_payload_{key}", value)
    return p


def main():
    parser = argparse.ArgumentParser(description="Simulador de telemetria ENTEL -> InfluxDB")
    parser.add_argument("interval", nargs="?", type=float, default=5.0,
                        metavar="SEGUNDOS", help="Intervalo entre envios (padrão: 5s)")
    parser.add_argument("--once", action="store_true", help="Envia um único ponto e sai")
    args = parser.parse_args()

    print(f"Conectando em {INFLUXDB_URL} (org={INFLUXDB_ORG}, bucket={INFLUXDB_BUCKET})")

    with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        print(f"Simulando mqtt_consumer | intervalo={args.interval}s | Ctrl+C para parar\n")

        try:
            while True:
                data  = generate_data()
                point = build_point(data)
                write_api.write(bucket=INFLUXDB_BUCKET, record=point)

                ts = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                print(
                    f"[{ts}]  "
                    f"V={data['tensao_v']:6.1f} V   "
                    f"I={data['corrente_a']:5.3f} A   "
                    f"P={data['potencia_w']:7.1f} W   "
                    f"E={data['energia_kwh']:.6f} kWh   "
                    f"f={data['freq_hz']:.1f} Hz   "
                    f"FP={data['fp']:.3f}"
                )

                if args.once:
                    print("\nEnvio único concluído.")
                    break

                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\nSimulação encerrada.")


if __name__ == "__main__":
    main()
