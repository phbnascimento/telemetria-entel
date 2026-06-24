#include <ModbusMaster.h>

// RS485
#define RS485_BAUD 9600
#define RS485_RX   5
#define RS485_TX   4
HardwareSerial RS485Serial(1);
ModbusMaster   node;

// LoRa (módulo AT via UART2)
#define LORA_BAUD 9600
#define LORA_RX   16
#define LORA_TX   17
HardwareSerial LoRaSerial(2);

#define LORA_PORT      1
#define INTERVALO_MS   30000UL
#define JOIN_RETRY_MS  15000UL

// Tokens de resposta ao AT+JOIN
#define JOIN_FAIL      "AT_JOIN_ERROR"
#define JOIN_SUCCESS   "AT_JOIN_OK"
#define JOIN_SUCCESS2  "AT_ALREADY_JOINED"

unsigned long ultima_leitura      = 0;
unsigned long ultimo_join_attempt = 0;
bool          lora_joined         = false;


void loraSend(const String& cmd) {
  LoRaSerial.println(cmd);
  Serial.println(">> " + cmd);
}

bool loraWait(const String& esperado, unsigned long timeout_ms = 10000) {
  String buf = "";
  unsigned long t = millis();
  while (millis() - t < timeout_ms) {
    while (LoRaSerial.available()) {
      char c = LoRaSerial.read();
      if (c == '\n') {
        buf.trim();
        if (buf.length()) Serial.println("<< " + buf);
        if (buf.indexOf(esperado) >= 0) return true;
        buf = "";
      } else if (c != '\r') {
        buf += c;
      }
    }
  }
  return false;
}

void loraDrain(unsigned long ms) {
  unsigned long t = millis();
  while (millis() - t < ms) {
    while (LoRaSerial.available()) Serial.write(LoRaSerial.read());
  }
}

bool loraJoin() {
  loraSend("AT+JOIN");
  String buf = "";
  unsigned long t = millis();
  while (millis() - t < 20000) {
    while (LoRaSerial.available()) {
      char c = LoRaSerial.read();
      if (c == '\n') {
        buf.trim();
        if (buf.length()) Serial.println("<< " + buf);
        if (buf.indexOf(JOIN_FAIL) >= 0) {
          Serial.println("Join rejeitado pelo módulo.");
          return false;
        }
        if (buf.indexOf(JOIN_SUCCESS) >= 0 || buf.indexOf(JOIN_SUCCESS2) >= 0) {
          Serial.println("Join OK.");
          return true;
        }
        buf = "";
      } else if (c != '\r') {
        buf += c;
      }
    }
  }
  Serial.println("Join timeout.");
  return false;
}

void loraEnviarPayload(const uint8_t* buf, uint8_t len) {
  String hex = "";
  for (int i = 0; i < len; i++) {
    if (buf[i] < 0x10) hex += "0";
    hex += String(buf[i], HEX);
  }
  loraSend("AT+SEND=" + String(LORA_PORT) + ":" + hex);
  if (!loraWait("AT_SENT", 8000)) {
    Serial.println("TX falhou — forçando rejoin");
    lora_joined = false;
  }
}

// Modbus -> payload
void lerEEnviar() {
  delay(50);
  uint8_t result = node.readHoldingRegisters(0x0000, 18);
  if (result != node.ku8MBSuccess) {
    Serial.println("Modbus erro: 0x" + String(result, HEX));
    return;
  }

  uint32_t e_raw    = ((uint32_t)node.getResponseBuffer(0) << 16) | node.getResponseBuffer(1);
  uint32_t energia  = e_raw * 10UL;
  uint16_t tensao   = node.getResponseBuffer(12);
  uint16_t corrente = (uint16_t)((uint32_t)node.getResponseBuffer(13) * 10);
  int16_t  potencia = (int16_t)node.getResponseBuffer(14);
  uint16_t freq     = node.getResponseBuffer(17);
  uint16_t fp       = node.getResponseBuffer(16);

  Serial.printf("[Modbus OK] V=%.1f V  I=%.3f A  P=%d W  E=%.3f kWh\n",
    tensao/10.0, corrente/1000.0, potencia, energia/1000.0);

  if (!lora_joined) {
    Serial.println("LoRa não conectado — leitura OK, payload descartado");
    return;
  }

  uint8_t buf[14];
  buf[0]  =  energia           & 0xFF;
  buf[1]  = (energia >>  8)    & 0xFF;
  buf[2]  = (energia >> 16)    & 0xFF;
  buf[3]  = (energia >> 24)    & 0xFF;
  buf[4]  = tensao             & 0xFF;
  buf[5]  = (tensao  >>  8)    & 0xFF;
  buf[6]  = corrente           & 0xFF;
  buf[7]  = (corrente >>  8)   & 0xFF;
  buf[8]  = (uint8_t)(potencia & 0xFF);
  buf[9]  = (uint8_t)((potencia >> 8) & 0xFF);
  buf[10] = freq               & 0xFF;
  buf[11] = (freq >> 8)        & 0xFF;
  buf[12] = fp                 & 0xFF;
  buf[13] = (fp >> 8)          & 0xFF;

  loraEnviarPayload(buf, 14);
}

void setup() {
  Serial.begin(115200);
  delay(200);

  RS485Serial.begin(RS485_BAUD, SERIAL_8N1, RS485_RX, RS485_TX);
  node.begin(1, RS485Serial);

  LoRaSerial.begin(LORA_BAUD, SERIAL_8N1, LORA_RX, LORA_TX);

  Serial.println("Aguardando boot do LoRa...");
  delay(5000);          // deixa o módulo terminar boot/auto-join antes do AT+JOIN
  loraDrain(500);       // descarta o banner de boot do buffer

  Serial.println("Join OTAA...");
  lora_joined = loraJoin();
  ultimo_join_attempt = millis();
}

void loop() {
  unsigned long agora = millis();

  // Retry join sem bloquear o loop
  if (!lora_joined && (agora - ultimo_join_attempt >= JOIN_RETRY_MS)) {
    ultimo_join_attempt = agora;
    Serial.println("Tentando novamente join OTAA...");
    lora_joined = loraJoin();
  }

  // Modbus roda independente do join
  if (agora - ultima_leitura >= INTERVALO_MS) {
    ultima_leitura = agora;
    lerEEnviar();
  }
}
