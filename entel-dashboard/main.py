import asyncio
import flet as ft
import flet_charts as fch
import time
from collections import deque

from influxdb_client import InfluxDBClient

import auth
import config_store
import notif_store

INFLUXDB_URL    = "http://localhost:8086"
INFLUXDB_TOKEN  = "entel-2026"
INFLUXDB_ORG    = "entel"
INFLUXDB_BUCKET = "telemetry"
POLL_INTERVAL   = 1
HIST_LEN        = 30
I_MAX           = 65.0


def main(page: ft.Page):
    page.title = "Dashboard de Telemetria"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.window.width = 1400

    _state = {"rodando": None, "influx": None, "role": None, "username": None}

    # ── Tela de login ──────────────────────────────────────────────────────────
    def mostrar_login():
        if _state["rodando"]:
            _state["rodando"][0] = False
        if _state["influx"]:
            _state["influx"].close()
            _state["influx"] = None

        page.clean()

        tf_user = ft.TextField(label="Usuário", autofocus=True, width=280)
        tf_pass = ft.TextField(
            label="Senha", password=True, can_reveal_password=True, width=280
        )
        erro = ft.Text("", color=ft.Colors.RED_400, size=13)

        def fazer_login(e=None):
            role = auth.authenticate(tf_user.value.strip(), tf_pass.value)
            if role:
                _state["role"]     = role
                _state["username"] = tf_user.value.strip()
                construir_dashboard()
            else:
                erro.value    = "Usuário ou senha incorretos"
                tf_pass.value = ""
                page.update()

        tf_user.on_submit = lambda e: tf_pass.focus()
        tf_pass.on_submit = fazer_login

        page.add(
            ft.Column(
                expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.ELECTRIC_BOLT, size=56, color=ft.Colors.CYAN_400),
                    ft.Text("Telemetria ENTEL", size=22, weight=ft.FontWeight.BOLD),
                    ft.Container(height=8),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                tf_user, tf_pass, erro,
                                ft.FilledButton("Entrar", on_click=fazer_login, width=280),
                            ],
                            spacing=12,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.2, ft.Colors.WHITE)),
                        border_radius=12,
                        padding=24,
                    ),
                ],
            )
        )

    # ── Dashboard ──────────────────────────────────────────────────────────────
    def construir_dashboard():
        is_admin = _state["role"] == "admin"

        # ── Estado ────────────────────────────────────────────────────────────
        v_hist: deque[float] = deque([220.0] * HIST_LEN, maxlen=HIST_LEN)
        i_hist: deque[float] = deque([0.0]   * HIST_LEN, maxlen=HIST_LEN)
        p_hist: deque[float] = deque([0.0]   * HIST_LEN, maxlen=HIST_LEN)
        _ndata              = notif_store.load()
        notificacoes: list[str] = [n["texto"] for n in _ndata["notificacoes"]]
        _max_notif          = [_ndata.get("max_count", 1000)]
        _ultimo_sem_dados   = [0.0]
        _ultimo_dado        = [0.0]
        _prev_ts            = [None]
        _device_start       = [None]
        _v_total            = [0.0]
        _v_count            = [0]
        _i_total            = [0.0]
        _i_count            = [0]
        _p_total            = [0.0]
        _p_count            = [0]
        del _ndata
        inicio          = time.time()
        rodando         = [True]
        subtitulos_card: list[ft.Text] = []

        _state["rodando"] = rodando

        config    = config_store.load()
        _poll_ms      = [config.get("poll_interval_ms", 1000)]
        alarme    = {"ativo": False, "silenciado": False, "fora_desde": None, "dentro_desde": None}

        # ── InfluxDB ──────────────────────────────────────────────────────────
        influx = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        _state["influx"] = influx
        query_api = influx.query_api()

        def buscar_dados() -> dict | None:
            _CAMPOS = {
                "uplink_message_decoded_payload_tensao_v":    "voltage",
                "uplink_message_decoded_payload_corrente_a":  "current",
                "uplink_message_decoded_payload_energia_kwh": "energy_kwh",
                "uplink_message_decoded_payload_potencia_w":  "power_w",
                "uplink_message_decoded_payload_freq_hz":     "freq_hz",
            }
            flux = f'''
            from(bucket: "{INFLUXDB_BUCKET}")
              |> range(start: -2m)
              |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
              |> filter(fn: (r) => r["_field"] == "uplink_message_decoded_payload_tensao_v" or
                                   r["_field"] == "uplink_message_decoded_payload_corrente_a" or
                                   r["_field"] == "uplink_message_decoded_payload_energia_kwh" or
                                   r["_field"] == "uplink_message_decoded_payload_potencia_w" or
                                   r["_field"] == "uplink_message_decoded_payload_freq_hz")
              |> last()
            '''
            try:
                tables = query_api.query(flux)
                result = {}
                ts     = None
                for table in tables:
                    for rec in table.records:
                        key = _CAMPOS.get(rec.get_field(), rec.get_field())
                        result[key] = rec.get_value()
                        ts = rec.get_time()
                if len(result) == 5:
                    result["_time"] = ts
                    return result
                return None
            except Exception:
                return None

        # ── Gráficos ──────────────────────────────────────────────────────────
        def make_pts(hist):
            poll_s = _poll_ms[0] / 1000.0
            n = len(hist)
            return [fch.LineChartDataPoint(-(n - 1 - i) * poll_s, round(v, 3))
                    for i, v in enumerate(hist)]

        linha_v = fch.LineChartData(
            color=ft.Colors.CYAN_400, stroke_width=2, curved=True,
            rounded_stroke_cap=True,
            below_line_bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.CYAN_400),
            points=make_pts(v_hist),
        )
        grafico_v = fch.LineChart(
            data_series=[linha_v], expand=True,
            min_y=180, max_y=260,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(
                interval=10, color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE)),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
        )

        linha_i = fch.LineChartData(
            color=ft.Colors.ORANGE_400, stroke_width=2, curved=True,
            rounded_stroke_cap=True,
            below_line_bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.ORANGE_400),
            points=make_pts(i_hist),
        )
        grafico_i = fch.LineChart(
            data_series=[linha_i], expand=True,
            min_y=0, max_y=50,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(
                interval=10, color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE)),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
        )

        linha_p = fch.LineChartData(
            color=ft.Colors.TEAL_400, stroke_width=2, curved=True,
            rounded_stroke_cap=True,
            below_line_bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.TEAL_400),
            points=make_pts(p_hist),
        )
        grafico_p = fch.LineChart(
            data_series=[linha_p], expand=True,
            min_y=0, max_y=3000,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(
                interval=500, color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE)),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
        )

        # ── Gráficos de barras ────────────────────────────────────────────────
        _grid_w = ft.Colors.with_opacity(0.15, ft.Colors.WHITE)
        _brd_w  = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.WHITE))

        def make_bar_v(hist):
            return [fch.BarChartGroup(x=i, rods=[fch.BarChartRod(
                from_y=200, to_y=round(v, 2), width=6,
                color=ft.Colors.CYAN_400, border_radius=2,
            )]) for i, v in enumerate(hist)]

        def make_bar_i(hist):
            return [fch.BarChartGroup(x=i, rods=[fch.BarChartRod(
                from_y=0, to_y=round(v, 3), width=6,
                color=ft.Colors.ORANGE_400, border_radius=2,
            )]) for i, v in enumerate(hist)]

        def make_bar_p(hist):
            return [fch.BarChartGroup(x=i, rods=[fch.BarChartRod(
                from_y=0, to_y=round(v, 1), width=6,
                color=ft.Colors.TEAL_400, border_radius=2,
            )]) for i, v in enumerate(hist)]

        grafico_barra_v = fch.BarChart(
            groups=make_bar_v(v_hist), expand=True,
            min_y=180, max_y=260,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(interval=10, color=_grid_w),
            border=_brd_w,
        )
        grafico_barra_i = fch.BarChart(
            groups=make_bar_i(i_hist), expand=True,
            min_y=0, max_y=50,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(interval=10, color=_grid_w),
            border=_brd_w,
        )
        grafico_barra_p = fch.BarChart(
            groups=make_bar_p(p_hist), expand=True,
            min_y=0, max_y=3000,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(interval=500, color=_grid_w),
            border=_brd_w,
        )

        # ── Gráficos de dispersão ─────────────────────────────────────────────
        def make_scatter_v(hist):
            poll_s = _poll_ms[0] / 1000.0
            n = len(hist)
            return [fch.ScatterChartSpot(x=-(n - 1 - i) * poll_s, y=round(v, 3),
                                         radius=4, color=ft.Colors.CYAN_400)
                    for i, v in enumerate(hist)]

        def make_scatter_i(hist):
            poll_s = _poll_ms[0] / 1000.0
            n = len(hist)
            return [fch.ScatterChartSpot(x=-(n - 1 - i) * poll_s, y=round(v, 3),
                                         radius=4, color=ft.Colors.ORANGE_400)
                    for i, v in enumerate(hist)]

        def make_scatter_p(hist):
            poll_s = _poll_ms[0] / 1000.0
            n = len(hist)
            return [fch.ScatterChartSpot(x=-(n - 1 - i) * poll_s, y=round(v, 1),
                                         radius=4, color=ft.Colors.TEAL_400)
                    for i, v in enumerate(hist)]

        grafico_scatter_v = fch.ScatterChart(
            spots=make_scatter_v(v_hist), expand=True,
            min_y=180, max_y=260,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(interval=10, color=_grid_w),
            border=_brd_w,
        )
        grafico_scatter_i = fch.ScatterChart(
            spots=make_scatter_i(i_hist), expand=True,
            min_y=0, max_y=50,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(interval=10, color=_grid_w),
            border=_brd_w,
        )
        grafico_scatter_p = fch.ScatterChart(
            spots=make_scatter_p(p_hist), expand=True,
            min_y=0, max_y=3000,
            left_axis=fch.ChartAxis(label_size=40),
            bottom_axis=fch.ChartAxis(label_size=24),
            horizontal_grid_lines=fch.ChartGridLines(interval=500, color=_grid_w),
            border=_brd_w,
        )

        # Containers que trocam de gráfico
        cont_v = ft.Container(content=grafico_v, expand=True)
        cont_i = ft.Container(content=grafico_i, expand=True)
        cont_p = ft.Container(content=grafico_p, expand=True)

        _graficos_v = {"linha": grafico_v, "barra": grafico_barra_v, "dispersao": grafico_scatter_v}
        _graficos_i = {"linha": grafico_i, "barra": grafico_barra_i, "dispersao": grafico_scatter_i}
        _graficos_p = {"linha": grafico_p, "barra": grafico_barra_p, "dispersao": grafico_scatter_p}

        sel_v = ft.SegmentedButton(
            segments=[
                ft.Segment(value="linha",     label=ft.Text("Linha")),
                ft.Segment(value="barra",     label=ft.Text("Barras")),
                ft.Segment(value="dispersao", label=ft.Text("Dispersão")),
            ],
            selected=["linha"],
            allow_empty_selection=False,
            allow_multiple_selection=False,
            on_change=lambda e: (
                cont_v.__setattr__("content", _graficos_v[e.control.selected[0]]),
                page.update(),
            ),
        )
        sel_i = ft.SegmentedButton(
            segments=[
                ft.Segment(value="linha",     label=ft.Text("Linha")),
                ft.Segment(value="barra",     label=ft.Text("Barras")),
                ft.Segment(value="dispersao", label=ft.Text("Dispersão")),
            ],
            selected=["linha"],
            allow_empty_selection=False,
            allow_multiple_selection=False,
            on_change=lambda e: (
                cont_i.__setattr__("content", _graficos_i[e.control.selected[0]]),
                page.update(),
            ),
        )
        sel_p = ft.SegmentedButton(
            segments=[
                ft.Segment(value="linha",     label=ft.Text("Linha")),
                ft.Segment(value="barra",     label=ft.Text("Barras")),
                ft.Segment(value="dispersao", label=ft.Text("Dispersão")),
            ],
            selected=["linha"],
            allow_empty_selection=False,
            allow_multiple_selection=False,
            on_change=lambda e: (
                cont_p.__setattr__("content", _graficos_p[e.control.selected[0]]),
                page.update(),
            ),
        )

        # ── Cards ─────────────────────────────────────────────────────────────
        txt_tensao   = ft.Text("--",       size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_400)
        txt_corrente = ft.Text("--",       size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_400)
        txt_potencia = ft.Text("--",       size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL_400)
        txt_energia  = ft.Text("--",       size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
        txt_freq     = ft.Text("--",       size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_300)
        txt_uptime   = ft.Text("00:00:00", size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
        txt_latencia = ft.Text("--",        size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_300)

        def card(titulo, valor_widget, cor):
            lbl = ft.Text(titulo, size=12, color=ft.Colors.WHITE54)
            subtitulos_card.append(lbl)
            return ft.Container(
                content=ft.Column(
                    [lbl, valor_widget],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=ft.Colors.with_opacity(0.15, cor),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.4, cor)),
                border_radius=10,
                padding=16,
                expand=True,
            )

        cards = ft.Row(
            controls=[
                card("Tensão (V)",     txt_tensao,   ft.Colors.CYAN_400),
                card("Corrente (A)",   txt_corrente, ft.Colors.ORANGE_400),
                card("Potência (W)",   txt_potencia, ft.Colors.TEAL_400),
                card("Energia (kWh)",  txt_energia,  ft.Colors.GREEN_400),
                card("Frequência (Hz)", txt_freq,    ft.Colors.BLUE_300),
                card("Última Leitura", txt_latencia, ft.Colors.PURPLE_300),
                card("Uptime",         txt_uptime,   ft.Colors.AMBER_400),
            ],
            spacing=12,
        )

        # ── Cards de média ────────────────────────────────────────────────────
        txt_media_v = ft.Text("-- V", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_400)
        txt_media_i = ft.Text("-- A", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_400)
        txt_media_p = ft.Text("-- W", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL_400)

        def reset_media_v(e=None):
            _v_total[0] = 0.0
            _v_count[0] = 0
            txt_media_v.value = "-- V"
            page.update()

        def reset_media_i(e=None):
            _i_total[0] = 0.0
            _i_count[0] = 0
            txt_media_i.value = "-- A"
            page.update()

        def reset_media_p(e=None):
            _p_total[0] = 0.0
            _p_count[0] = 0
            txt_media_p.value = "-- W"
            page.update()

        def _card_media(titulo, valor_widget, cor, on_reset):
            lbl = ft.Text(titulo, size=12, color=ft.Colors.WHITE54)
            subtitulos_card.append(lbl)
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        lbl,
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_size=16,
                            icon_color=ft.Colors.with_opacity(0.7, cor),
                            tooltip="Resetar média",
                            on_click=on_reset,
                        ),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    valor_widget,
                ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.with_opacity(0.15, cor),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.4, cor)),
                border_radius=10,
                padding=ft.Padding(left=16, right=4, top=8, bottom=12),
                expand=True,
            )

        cards_media = ft.Row(
            controls=[
                _card_media("Média Tensão (V)",   txt_media_v, ft.Colors.CYAN_400,   reset_media_v),
                _card_media("Média Corrente (A)", txt_media_i, ft.Colors.ORANGE_400, reset_media_i),
                _card_media("Média Potência (W)", txt_media_p, ft.Colors.TEAL_400,   reset_media_p),
            ],
            spacing=12,
        )

        # ── Notificações ──────────────────────────────────────────────────────
        lista_notif = ft.ListView(expand=True, spacing=6, padding=10)

        def _cor_notif():
            return ft.Colors.WHITE70 if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.BLACK

        def _rebuild_lista_notif():
            cor = _cor_notif()
            lista_notif.controls.clear()
            for n in notificacoes[:500]:
                lista_notif.controls.append(
                    ft.Container(
                        content=ft.Text(n, size=12, color=cor),
                        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.WHITE),
                        border_radius=6,
                        padding=10,
                    )
                )

        def adicionar_notif(msg: str):
            ts_full  = time.strftime("%Y-%m-%d %H:%M:%S")
            ts_short = time.strftime("%Y/%m/%d %H:%M:%S")
            entrada  = f"[{ts_short}] {msg}"
            notificacoes.insert(0, entrada)
            while len(notificacoes) > _max_notif[0]:
                notificacoes.pop()
            notif_store.add(ts_full, entrada)
            _rebuild_lista_notif()
            page.update()

        # ── Alarme ────────────────────────────────────────────────────────────
        def silenciar_alarme(e=None):
            alarme["ativo"]      = False
            alarme["silenciado"] = True
            alarme["fora_desde"] = None
            banner_alarme.visible        = False
            btn_silenciar_config.visible = False
            adicionar_notif("🔇 Alarme silenciado manualmente")
            page.update()

        def verificar_alarme(v: float):
            agora   = time.time()
            v_min   = config["v_min"]
            v_max   = config["v_max"]
            hist    = config["histerese"]
            fora    = v < v_min or v > v_max
            na_hist = (v_min + v_min * hist / 100.0) <= v <= (v_max - v_max * hist / 100.0)

            if fora:
                alarme["dentro_desde"] = None
                if alarme["fora_desde"] is None:
                    alarme["fora_desde"] = agora
                tempo_fora = agora - alarme["fora_desde"]
                if tempo_fora >= 1.0 and not alarme["ativo"] and not alarme["silenciado"]:
                    alarme["ativo"] = True
                    tipo = "SUBTENSÃO" if v < v_min else "SOBRETENSÃO"
                    banner_txt.value             = f"🚨 {tipo}: {v:.1f} V"
                    banner_alarme.visible        = True
                    btn_silenciar_config.visible = True
                    adicionar_notif(f"🚨 {tipo}: {v:.1f} V — fora dos limites por {tempo_fora:.1f}s")
            else:
                alarme["fora_desde"] = None

                # Alarme silenciado: tensão voltou ao limite → limpa flag para
                # que a próxima ocorrência dispare normalmente como novo evento.
                if alarme["silenciado"] and not alarme["ativo"]:
                    alarme["silenciado"]   = False
                    alarme["dentro_desde"] = None

                # Alarme ativo: aguarda histerese por 10s para desarmar.
                if alarme["ativo"]:
                    if na_hist:
                        if alarme["dentro_desde"] is None:
                            alarme["dentro_desde"] = agora
                        elif agora - alarme["dentro_desde"] >= 10.0:
                            alarme["ativo"]        = False
                            alarme["silenciado"]   = False
                            alarme["fora_desde"]   = None
                            alarme["dentro_desde"] = None
                            banner_alarme.visible        = False
                            btn_silenciar_config.visible = False
                            adicionar_notif("✅ Tensão normalizada — alarme encerrado")
                    else:
                        alarme["dentro_desde"] = None

        # ── Atualização ───────────────────────────────────────────────────────
        def atualizar(dados: dict):
            v = float(dados["voltage"])
            i = float(dados["current"])
            e = float(dados["energy_kwh"])
            p = float(dados["power_w"])
            f = float(dados["freq_hz"])

            v_hist.append(v)
            i_hist.append(i)
            p_hist.append(p)

            linha_v.points          = make_pts(v_hist)
            linha_i.points          = make_pts(i_hist)
            linha_p.points          = make_pts(p_hist)
            grafico_barra_v.groups  = make_bar_v(v_hist)
            grafico_barra_i.groups  = make_bar_i(i_hist)
            grafico_barra_p.groups  = make_bar_p(p_hist)
            grafico_scatter_v.spots = make_scatter_v(v_hist)
            grafico_scatter_i.spots = make_scatter_i(i_hist)
            grafico_scatter_p.spots = make_scatter_p(p_hist)

            txt_tensao.value   = f"{v:.1f} V"
            txt_corrente.value = f"{i:.3f} A"
            txt_potencia.value = f"{p:.1f} W"
            txt_energia.value  = f"{e:.6f}"
            txt_freq.value     = f"{f:.1f} Hz"

            _v_total[0] += v
            _v_count[0] += 1
            _i_total[0] += i
            _i_count[0] += 1
            _p_total[0] += p
            _p_count[0] += 1
            txt_media_v.value = f"{_v_total[0] / _v_count[0]:.2f} V"
            txt_media_i.value = f"{_i_total[0] / _i_count[0]:.3f} A"
            txt_media_p.value = f"{_p_total[0] / _p_count[0]:.1f} W"

            verificar_alarme(v)
            if i > I_MAX:
                adicionar_notif(f"⚠️ Corrente alta: {i:.3f} A (limite {I_MAX} A)")

        # ── Loop de polling ───────────────────────────────────────────────────
        async def loop():
            loop_ = asyncio.get_running_loop()
            while rodando[0]:
                await asyncio.sleep(_poll_ms[0] / 1000.0)
                try:
                    dados = await loop_.run_in_executor(None, buscar_dados)

                    if dados:
                        if dados["_time"] != _prev_ts[0]:
                            _prev_ts[0]     = dados["_time"]
                            _ultimo_dado[0] = time.time()
                            if _device_start[0] is None:
                                _device_start[0] = time.time()
                        atualizar(dados)

                    if _ultimo_dado[0]:
                        seg = int(time.time() - _ultimo_dado[0])
                        if seg < 60:
                            txt_latencia.value = f"{seg}s"
                        elif seg < 3600:
                            m, s = divmod(seg, 60)
                            txt_latencia.value = f"{m}m {s}s"
                        else:
                            h, m = divmod(seg // 60, 60)
                            txt_latencia.value = f"{h}h {m}m"
                    else:
                        agora_sd = time.time()
                        if agora_sd - _ultimo_sem_dados[0] >= 10.0:
                            _ultimo_sem_dados[0] = agora_sd
                            adicionar_notif("⚠️ Sem dados recentes no InfluxDB")

                    sem_dado = (time.time() - _ultimo_dado[0]) if _ultimo_dado[0] else None
                    if sem_dado is None or sem_dado > 30:
                        _device_start[0] = None
                        txt_uptime.value = "Desativado"
                    else:
                        elapsed = int(time.time() - _device_start[0])
                        h, rem  = divmod(elapsed, 3600)
                        m, s    = divmod(rem, 60)
                        txt_uptime.value = f"{h:02}:{m:02}:{s:02}"

                    page.update()
                except Exception:
                    break

        # ── Tema ──────────────────────────────────────────────────────────────
        def on_tema_change(e):
            escuro = e.control.value
            page.theme_mode = ft.ThemeMode.DARK if escuro else ft.ThemeMode.LIGHT
            cor_sub = ft.Colors.WHITE54 if escuro else ft.Colors.BLACK
            for lbl in subtitulos_card:
                lbl.color = cor_sub
            _rebuild_lista_notif()
            page.update()

        # ── Banner de alarme ──────────────────────────────────────────────────
        banner_txt    = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        banner_alarme = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WARNING_ROUNDED, color=ft.Colors.WHITE, size=20),
                    banner_txt,
                    ft.Container(expand=True),
                    ft.TextButton(
                        "Silenciar",
                        on_click=silenciar_alarme,
                        style=ft.ButtonStyle(color=ft.Colors.WHITE),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            bgcolor=ft.Colors.RED_700,
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            margin=ft.Margin(left=16, right=16, top=0, bottom=4),
            border_radius=8,
            visible=False,
        )

        # ── Controles de config (admin) ───────────────────────────────────────
        tf_poll = ft.TextField(
            label="Intervalo de leitura (ms)", value=str(config["poll_interval_ms"]),
            keyboard_type=ft.KeyboardType.NUMBER, width=200,
            read_only=not is_admin,
        )
        tf_vmin = ft.TextField(
            label="Tensão mínima (V)", value=str(config["v_min"]),
            keyboard_type=ft.KeyboardType.NUMBER, width=160,
            read_only=not is_admin,
        )
        tf_vmax = ft.TextField(
            label="Tensão máxima (V)", value=str(config["v_max"]),
            keyboard_type=ft.KeyboardType.NUMBER, width=160,
            read_only=not is_admin,
        )
        tf_hist = ft.TextField(
            label="Histerese (%)", value=str(config["histerese"]),
            keyboard_type=ft.KeyboardType.NUMBER, width=160,
            read_only=not is_admin,
        )
        btn_silenciar_config = ft.OutlinedButton(
            "Silenciar alarme",
            icon=ft.Icons.NOTIFICATIONS_OFF,
            on_click=silenciar_alarme,
            visible=False,
            style=ft.ButtonStyle(color=ft.Colors.RED_400),
        )

        def salvar_config(e):
            try:
                poll_ms = int(tf_poll.value)
                v_min   = float(tf_vmin.value.replace(",", "."))
                v_max   = float(tf_vmax.value.replace(",", "."))
                hist    = float(tf_hist.value.replace(",", "."))
            except ValueError:
                adicionar_notif("❌ Valores inválidos")
                page.update()
                return
            if poll_ms < 100:
                adicionar_notif("❌ Intervalo mínimo: 100 ms")
                page.update()
                return
            if v_min >= v_max:
                adicionar_notif("❌ Tensão mínima deve ser menor que a máxima")
                page.update()
                return

            def _aplicar(e):
                config["poll_interval_ms"] = poll_ms
                config["v_min"]            = v_min
                config["v_max"]            = v_max
                config["histerese"]        = hist
                _poll_ms[0]                = poll_ms
                config_store.save(config)
                adicionar_notif(
                    f"⚙️ Config salva: leitura={poll_ms} ms, "
                    f"limites={v_min}–{v_max} V, histerese={hist}%"
                )
                page.update()

            _confirmar(
                "Salvar configurações",
                f"Aplicar: leitura={poll_ms} ms, limites={v_min}–{v_max} V, histerese={hist}%?",
                _aplicar,
            )

        # ── E-mail ────────────────────────────────────────────────────────────
        tf_email = ft.TextField(
            label="E-mail para recepção de alarmes",
            value=auth.get_email(_state["username"]),
            width=320,
            keyboard_type=ft.KeyboardType.EMAIL,
        )

        cb_notif = ft.Checkbox(
            label="Receber e-mails",
            value=auth.get_notif_ativa(_state["username"]),
        )

        def on_notif_change(e):
            auth.update_notif_ativa(_state["username"], cb_notif.value)
            estado = "ativadas" if cb_notif.value else "desativadas"
            adicionar_notif(f"📧 Notificações por e-mail {estado}")
            page.update()

        cb_notif.on_change = on_notif_change

        def salvar_email(e):
            email = tf_email.value.strip()
            if "@" not in email or "." not in email.split("@")[-1]:
                adicionar_notif("❌ E-mail inválido")
                page.update()
                return
            auth.update_email(_state["username"], email)
            adicionar_notif(f"📧 E-mail atualizado: {email}")
            page.update()

        def fazer_logout(e):
            rodando[0] = False
            mostrar_login()

        # ── Diálogo de confirmação ────────────────────────────────────────────
        def _confirmar(titulo: str, mensagem: str, on_sim):
            def fechar(e):
                page.pop_dialog()
            def confirmar(e):
                page.pop_dialog()
                on_sim(e)
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(titulo, weight=ft.FontWeight.BOLD),
                content=ft.Text(mensagem),
                actions=[
                    ft.TextButton("Cancelar",  on_click=fechar),
                    ft.FilledButton("Confirmar", on_click=confirmar),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        # ── Gerenciamento de notificações ─────────────────────────────────────
        def on_max_notif_change(e):
            n = int(e.control.value)
            _max_notif[0] = n
            notif_store.set_max_count(n)
            while len(notificacoes) > n:
                notificacoes.pop()
            _rebuild_lista_notif()
            adicionar_notif(f"⚙️ Limite de histórico: {n} notificações")

        def limpar_notif_tudo(e):
            def _executar(e):
                notificacoes.clear()
                notif_store.clear_all()
                _rebuild_lista_notif()
                adicionar_notif("🗑️ Histórico de notificações limpo")
            _confirmar(
                "Limpar notificações",
                "Deseja apagar todo o histórico? Esta ação não pode ser desfeita.",
                _executar,
            )

        def limpar_notif_antigos(e):
            notif_store.clear_old(10)
            data = notif_store.load()
            notificacoes.clear()
            notificacoes.extend(n["texto"] for n in data["notificacoes"])
            _rebuild_lista_notif()
            adicionar_notif("🗑️ Notificações com mais de 10 dias removidas")

        rg_max_notif = ft.RadioGroup(
            content=ft.Row([
                ft.Radio(value="100",   label="100"),
                ft.Radio(value="1000",  label="1000"),
                ft.Radio(value="10000", label="10000"),
            ]),
            value=str(_max_notif[0]),
            on_change=on_max_notif_change,
        )

        # ── Abas ──────────────────────────────────────────────────────────────
        aba_dashboard = ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    content=ft.Text("Telemetria em Tempo Real", size=18, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
                ),
                banner_alarme,
                ft.Container(
                    content=cards,
                    padding=ft.Padding.only(left=16, right=16),
                ),
                ft.Container(
                    content=ft.Row(
                        spacing=12,
                        expand=True,
                        controls=[
                            ft.Column(expand=True, spacing=4, controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text("Tensão (V)", size=12, color=ft.Colors.CYAN_400),
                                        ft.Container(expand=True),
                                        sel_v,
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                cont_v,
                            ]),
                            ft.Column(expand=True, spacing=4, controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text("Corrente (A)", size=12, color=ft.Colors.ORANGE_400),
                                        ft.Container(expand=True),
                                        sel_i,
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                cont_i,
                            ]),
                            ft.Column(expand=True, spacing=4, controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text("Potência (W)", size=12, color=ft.Colors.TEAL_400),
                                        ft.Container(expand=True),
                                        sel_p,
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                cont_p,
                            ]),
                        ],
                    ),
                    height=310,
                    padding=ft.Padding.only(left=16, right=16, top=16, bottom=8),
                ),
                ft.Container(
                    content=cards_media,
                    padding=ft.Padding.only(left=16, right=16, top=4, bottom=12),
                ),
            ],
        )

        aba_notif = ft.Column(
            expand=True,
            controls=[
                ft.Container(
                    content=ft.Text("Notificações", size=18, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
                ),
                ft.Container(content=lista_notif, expand=True),
            ],
        )

        config_section = ft.Column(
            controls=[
                ft.Divider(height=24),
                ft.Container(
                    content=ft.Text("Histórico de Notificações", size=14, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.only(left=16, bottom=4),
                ),
                ft.Container(
                    content=ft.Row([
                        ft.Text("Armazenar últimas:", size=13),
                        rg_max_notif,
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                    padding=ft.Padding.only(left=16, right=16, bottom=4),
                ),
                ft.Container(
                    content=ft.Row([
                        ft.OutlinedButton(
                            "Limpar tudo",
                            icon=ft.Icons.DELETE_SWEEP,
                            on_click=limpar_notif_tudo,
                            style=ft.ButtonStyle(color=ft.Colors.RED_400),
                        ),
                        ft.OutlinedButton(
                            "Limpar > 10 dias",
                            icon=ft.Icons.HISTORY,
                            on_click=limpar_notif_antigos,
                        ),
                    ], spacing=12),
                    padding=ft.Padding.only(left=16, right=16, bottom=4),
                ),
                ft.Divider(height=24),
                ft.Container(
                    content=ft.Text("Notificações por E-mail", size=14, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.only(left=16, bottom=8),
                ),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            tf_email,
                            cb_notif,
                            ft.FilledButton("Salvar", icon=ft.Icons.SAVE, on_click=salvar_email),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.only(left=16, right=16, bottom=4),
                ),
                ft.Divider(height=24),
                ft.Container(
                    content=ft.Text("Intervalo de Leitura e Limites de Tensão", size=14, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.only(left=16, bottom=8),
                ),
                ft.Container(
                    content=ft.Row(
                        controls=[tf_poll, tf_vmin, tf_vmax, tf_hist],
                        spacing=12, wrap=True,
                    ),
                    padding=ft.Padding.only(left=16, right=16),
                ),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.FilledButton(
                                "Salvar", icon=ft.Icons.SAVE,
                                on_click=salvar_config,
                                disabled=not is_admin,
                            ),
                            btn_silenciar_config,
                        ],
                        spacing=12,
                    ),
                    padding=ft.Padding.only(left=16, top=12),
                ),
                ft.Container(
                    content=ft.Text(
                        "Apenas o administrador pode alterar estas configurações.",
                        size=11, color=ft.Colors.WHITE54, italic=True,
                    ),
                    padding=ft.Padding.only(left=16, top=4),
                    visible=not is_admin,
                ),
            ],
        )

        aba_config = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text("Configurações", size=18, weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            ft.TextButton(
                                f"Sair ({_state['role']})",
                                icon=ft.Icons.LOGOUT,
                                on_click=fazer_logout,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
                ),
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.DARK_MODE),
                    title=ft.Text("Tema escuro"),
                    trailing=ft.Switch(value=True, on_change=on_tema_change),
                ),
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.STORAGE),
                    title=ft.Text("InfluxDB"),
                    subtitle=ft.Text(INFLUXDB_URL, size=11, color=ft.Colors.WHITE54),
                ),
                config_section,
            ],
        )

        tabs = ft.Tabs(
            length=3,
            selected_index=0,
            expand=1,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=[
                        ft.Tab(label="Dashboard",     icon=ft.Icons.DASHBOARD),
                        ft.Tab(label="Notificações",  icon=ft.Icons.NOTIFICATIONS),
                        ft.Tab(label="Configurações", icon=ft.Icons.SETTINGS),
                    ]),
                    ft.TabBarView(
                        expand=True,
                        controls=[aba_dashboard, aba_notif, aba_config],
                    ),
                ],
            ),
        )

        page.clean()
        page.add(tabs)
        page.run_task(loop)
        page.on_close = lambda _: rodando.__setitem__(0, False)
        adicionar_notif(f"✅ Sessão iniciada como '{_state['role']}'")

    mostrar_login()


ft.run(main)
