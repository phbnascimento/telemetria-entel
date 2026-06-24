function decodeUplink(input) {
    var raw = input.bytes;

    var b = [];
    for (var i = 0; i < raw.length; i += 2) {
        b.push(parseInt(String.fromCharCode(raw[i], raw[i + 1]), 16));
    }

    var energia_kwh = ((b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24) >>> 0) /
        1000.0;
    var tensao_v = (b[4] | b[5] << 8) / 10.0;
    var corrente_a = (b[6] | b[7] << 8) / 1000.0;
    var potencia_w = b[8] | b[9] << 8;
    if (potencia_w >= 32768) potencia_w -= 65536;
    var freq_hz = (b[10] | b[11] << 8) / 100.0;
    var fp = (b[12] | b[13] << 8) / 1000.0;

    return {
        data: {
            energia_kwh: energia_kwh,
            tensao_v: tensao_v,
            corrente_a: corrente_a,
            potencia_w: potencia_w,
            freq_hz: freq_hz,
            fp: fp,
        },
    };
}
