#!/usr/bin/env python3
"""
Simula envio de dados de telemetria de um ESP32 + DDS para o InfluxDB.

Measurements:
  - power: voltage (V), current (A), energy_mwh (mWh acumulado)

Usage:
  python simulate_data.py          # roda continuamente, intervalo padrão 5s
  python simulate_data.py 3        # intervalo de 3s
  python simulate_data.py --once   # envia um único ponto e sai
  python simulate_data.py --once 3 # único ponto, mas mostra o intervalo configurado
"""

import argparse
import math
import random
import time
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUXDB_URL    = "http://localhost:8086"
INFLUXDB_TOKEN  = "entel-super-secret-token-influx-2024"
INFLUXDB_ORG    = "entel"
INFLUXDB_BUCKET = "telemetry"

DEVICE_ID = "esp32_001"

_energy_kwh = 0.0
_last_tick  = time.time()


def _sine_noise(base: float, amplitude: float, period_s: float, noise: float) -> float:
    t = time.time()
    return base + amplitude * math.sin(2 * math.pi * t / period_s) + random.uniform(-noise, noise)


def generate_power_data(interval_s: float) -> dict:
    global _energy_kwh, _last_tick

    voltage = round(_sine_noise(220.0, 2.0, 120, 0.5), 2)   # 220V ±2V + ruído
    current = round(max(0.0, _sine_noise(1.5, 0.8, 180, 0.1)), 3)  # ~0.7–2.3A

    # energia acumulada: P(W) × dt(h) / 1000 → kWh
    now = time.time()
    dt_h = (now - _last_tick) / 3600.0
    _last_tick = now
    _energy_kwh += voltage * current * dt_h / 1000

    return {
        "voltage":    voltage,
        "current":    current,
        "energy_kwh": round(_energy_kwh, 6),
    }


def build_point(data: dict) -> Point:
    return (
        Point("power")
        .tag("device_id", DEVICE_ID)
        .field("voltage",    data["voltage"])
        .field("current",    data["current"])
        .field("energy_kwh", data["energy_kwh"])
        .time(datetime.now(timezone.utc), "s")
    )


def main():
    parser = argparse.ArgumentParser(description="Simulador de telemetria ESP32+DDS → InfluxDB")
    parser.add_argument("interval", nargs="?", type=float, default=5.0,
                        metavar="SEGUNDOS", help="Intervalo entre envios em segundos (padrão: 5)")
    parser.add_argument("--once", action="store_true", help="Envia um único ponto e sai")
    args = parser.parse_args()

    print(f"Conectando em {INFLUXDB_URL} (org={INFLUXDB_ORG}, bucket={INFLUXDB_BUCKET})")

    with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        print(f"Simulando device_id={DEVICE_ID} | intervalo={args.interval}s | Ctrl+C para parar\n")

        try:
            while True:
                data  = generate_power_data(args.interval)
                point = build_point(data)

                write_api.write(bucket=INFLUXDB_BUCKET, record=point)

                now = datetime.now().strftime("%H:%M:%S")
                power_w = round(data["voltage"] * data["current"], 2)
                print(
                    f"[{now}]  "
                    f"tensão={data['voltage']:6.2f} V   "
                    f"corrente={data['current']:5.3f} A   "
                    f"potência={power_w:7.2f} W   "
                    f"energia={data['energy_kwh']:.6f} kWh"
                )

                if args.once:
                    print("\nEnvio único concluído.")
                    break

                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\nSimulação encerrada.")


if __name__ == "__main__":
    main()
