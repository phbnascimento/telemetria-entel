/*
 * test_ble — DDS238 via Modbus → BLE UART (Nordic UART Service)
 *
 * Conecte no celular com qualquer app BLE UART:
 *   Android : "Serial Bluetooth Terminal"  ou  "nRF Connect"
 *   iOS     : "LightBlue"  ou  "nRF Connect"
 *
 * Procure o dispositivo "ENTEL-test" e subscreva a característica TX.
 * Os dados chegam como texto a cada 3 segundos.
 *
 * Bibliotecas: ModbusMaster (Doc Walker)  — BLE é nativa do ESP32
 */

#include <ModbusMaster.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// RS485 — mesmos pinos do firmware principal
#define RS485_BAUD 9600
#define RS485_RX   5
#define RS485_TX   4
HardwareSerial RS485Serial(1);
ModbusMaster   node;

// HM-10 compatible — reconhecido automaticamente pelo Serial Bluetooth Terminal
#define NUS_SERVICE "0000FFE0-0000-1000-8000-00805F9B34FB"
#define NUS_TX      "0000FFE1-0000-1000-8000-00805F9B34FB"

BLECharacteristic* pTx        = nullptr;
bool               conectado   = false;
unsigned long      ultima      = 0;

class CBs : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    conectado = true;
    Serial.println("BLE: celular conectado");
  }
  void onDisconnect(BLEServer* s) override {
    conectado = false;
    Serial.println("BLE: desconectado — anunciando novamente...");
    s->startAdvertising();
  }
};

void bleSend(const String& msg) {
  if (!conectado || !pTx) return;
  pTx->setValue((uint8_t*)msg.c_str(), msg.length());
  pTx->notify();
}

void setup() {
  Serial.begin(115200);
  delay(200);

  RS485Serial.begin(RS485_BAUD, SERIAL_8N1, RS485_RX, RS485_TX);
  node.begin(1, RS485Serial);

  BLEDevice::init("ENTEL-test");
  BLEServer*  srv = BLEDevice::createServer();
  srv->setCallbacks(new CBs());

  BLEService* svc = srv->createService(NUS_SERVICE);
  pTx = svc->createCharacteristic(NUS_TX,
          BLECharacteristic::PROPERTY_NOTIFY |
          BLECharacteristic::PROPERTY_READ   |
          BLECharacteristic::PROPERTY_WRITE_NR);
  pTx->addDescriptor(new BLE2902());
  svc->start();

  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(NUS_SERVICE);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();

  Serial.println("BLE pronto — aguardando celular (ENTEL-test)");
}

void loop() {
  if (millis() - ultima < 3000) return;
  ultima = millis();

  delay(50);
  uint8_t result = node.readHoldingRegisters(0x0000, 18);

  if (result != node.ku8MBSuccess) {
    String err = "Modbus erro: 0x" + String(result, HEX) + "\n";
    Serial.print(err);
    bleSend(err);
    return;
  }

  uint32_t e_raw  = ((uint32_t)node.getResponseBuffer(0) << 16) | node.getResponseBuffer(1);
  float energia   = e_raw / 100.0f;
  float tensao    = node.getResponseBuffer(12) / 10.0f;
  float corrente  = node.getResponseBuffer(13) / 100.0f;
  float potencia  = (int16_t)node.getResponseBuffer(14);
  float fp        = node.getResponseBuffer(16) / 1000.0f;
  float freq      = node.getResponseBuffer(17) / 100.0f;

  char buf[128];
  snprintf(buf, sizeof(buf),
    "V=%.1fV  I=%.3fA  P=%.1fW\nE=%.4fkWh  FP=%.3f  F=%.2fHz\n",
    tensao, corrente, potencia, energia, fp, freq);

  Serial.print(buf);
  bleSend(String(buf));
}
