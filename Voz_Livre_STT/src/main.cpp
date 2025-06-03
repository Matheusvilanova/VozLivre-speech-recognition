#include <WiFi.h>
#include <WiFiUdp.h>

// --- Configurações de Wi-Fi ---
const char* ssid = "SEU_WIFI";
const char* password = "SUA_SENHA";

// --- Configurações do Servidor UDP ---
const char* udpAddress = "192.168.1.100"; // Ex: "192.168.1.100"
const int udpPort = 12345; // Porta que o servidor estará escutando

// --- Configurações de Áudio ---
const int adcPin = 34; // Pino ADC conectado à saída do LM386
// Para uma amostragem mais consistente, interrupções de timer seriam melhores,
// mas para simplicidade, usaremos um pequeno delay.
// Taxa de amostragem aproximada (ajuste o delay e o tamanho do buffer conforme necessário)
const int sampleRate = 8000; // Amostras por segundo (Hz)
const int delayTime = 1000000 / sampleRate;

WiFiUDP udp;
uint8_t audioBuffer[128]; // Buffer para amostras de áudio (8-bit)
int bufferIndex = 0;

void setup() {
  Serial.begin(115200);

  // Configurar ADC (opcional, mas bom para consistência)
  // adcAttachPin(adcPin);
  // analogReadResolution(10); // 10-bit (0-1023). Padrão é 12-bit (0-4095)
  // analogSetAttenuation(ADC_11db); // Permite ler até ~3.3V

  // --- Conectar ao Wi-Fi ---
  WiFi.begin(ssid, password);
  Serial.print("Conectando ao WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("\nConectado!");
  Serial.print("Endereço IP do ESP32: ");
  Serial.println(WiFi.localIP());

  int adcValue = analogRead(34); 
  Serial.println(adcValue); // Imprime o valor lido
  delay(50);

  // --- Iniciar UDP ---
  if (udp.begin(WiFi.localIP(), udpPort)) { // Pode usar qualquer porta local disponível ou 0
    Serial.println("UDP iniciado.");
  } else {
    Serial.println("Falha ao iniciar UDP.");
  }
}

void loop() {
  // Ler valor do ADC
  int adcValue = analogRead(adcPin); // 0-4095 (se 12-bit)

  // Mapear para 8-bit (0-255) - ajuste conforme a saída real do seu LM386
  // O sinal de áudio é AC, então ele varia acima e abaixo de um ponto central.
  // Se o seu LM386 estiver bem configurado e o sinal ocupar boa parte da faixa do ADC,
  // você pode simplesmente pegar os 8 bits mais significativos ou escalar.
  // Exemplo simples de escalonamento (pode precisar de ajuste/calibração):
  uint8_t sample = map(adcValue, 0, 4095, 0, 255);
  // Ou, se o sinal estiver centrado em VCC/2 (aprox. 2048 para 12-bit ADC):
  // int16_t signedSample = adcValue - 2048; // Exemplo se quiser amostras com sinal
  // sample = (uint8_t)((signedSample >> 4) + 128); // Converter para 8-bit sem sinal

  audioBuffer[bufferIndex++] = sample;

  if (bufferIndex == sizeof(audioBuffer)) {
    // Enviar buffer cheio via UDP
    udp.beginPacket(udpAddress, udpPort);
    udp.write(audioBuffer, sizeof(audioBuffer));
    udp.endPacket();
    bufferIndex = 0; // Resetar índice do buffer
    // Serial.println("Pacote de áudio enviado");
  }

  delayMicroseconds(delayTime); // Controla a taxa de amostragem
}
