#include <WiFi.h>
#include <WiFiClient.h>
 
// --- Suas configurações ---
const char* ssid = "SEU_SSID";
const char* password = "SUA_SENHA";
const char* serverAddress = "SEU_IP";
const int serverPort = 12345;

// --- Configurações de Áudio e Hardware ---
const int sampleRate = 8000;
const int delayBetweenSamples = 1000000 / sampleRate; // 125 us
const int adcPin = 35;
const int pushToTalkButtonPin = 23;

size_t recordedAudioSize = 0;

// --- Buffer de Gravação ---
const int RECORDING_SECONDS = 10; // Grave por até 10 segundos
const int RECORD_BUFFER_SIZE = sampleRate * RECORDING_SECONDS; // 8000 * 10 = 80000 bytes
byte* audioBuffer = NULL; // O buffer será alocado dinamicamente

WiFiClient client;

// --- Estados do Programa ---
enum State { IDLE, RECORDING, SENDING };
State currentState = IDLE;

void setup() {
  Serial.begin(115200);
  pinMode(pushToTalkButtonPin, INPUT_PULLUP);

  // Aloca o buffer de áudio na memória RAM
  audioBuffer = (byte*) malloc(RECORD_BUFFER_SIZE);
  if (audioBuffer == NULL) {
    Serial.println("Falha ao alocar memória para o buffer de áudio!");
    while(1); // Trava aqui se não houver memória
  }

  // --- Conexão Wi-Fi ---
  WiFi.begin(ssid, password);
  Serial.print("Conectando ao WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Conectado!");
  Serial.print("Endereço IP: ");
  Serial.println(WiFi.localIP());
  Serial.println("Estado: AGUARDANDO. Pressione o botão para gravar.");
}

void loop() {
  switch (currentState) {
    case IDLE:
      // Se o botão for pressionado, muda para o estado de gravação
      if (digitalRead(pushToTalkButtonPin) == LOW) {
        Serial.println("Estado: GRAVANDO... Solte para enviar.");
        currentState = RECORDING;
      }
      break;

    case RECORDING: { // Usamos chaves aqui para criar um escopo local para as novas variáveis
      // --- LÓGICA DE TIMING PRECISO ---
      unsigned long next_sample_time_us = micros();
      const unsigned long sample_period_us = 1000000 / sampleRate; // 125 microssegundos

      recordedAudioSize = 0; // Reseta o tamanho antes de iniciar

      for (int i = 0; i < RECORD_BUFFER_SIZE; i++) {
        // Se o botão for solto, para a gravação
        if (digitalRead(pushToTalkButtonPin) == HIGH) {
          recordedAudioSize = i; // Salva o número de bytes realmente gravados
          break; 
        }
        
        // ESPERA ATÉ O MOMENTO EXATO DA PRÓXIMA AMOSTRA
        while (micros() < next_sample_time_us) {
          // Espera ativa (busy-waiting). Não faz nada até a hora certa.
        }
        
        // Captura a amostra
        int adcValue = analogRead(adcPin);
        audioBuffer[i] = map(adcValue, 0, 4095, 0, 255);
        
        // Calcula o tempo para a PRÓXIMA amostra
        next_sample_time_us += sample_period_us;
      }
      
      // Se saiu do loop, a gravação terminou
      if (recordedAudioSize == 0) { // Se não quebrou antes, o buffer encheu
        recordedAudioSize = RECORD_BUFFER_SIZE;
      }
      Serial.print("Gravação finalizada. ");
      Serial.print(recordedAudioSize / (float)sampleRate, 2);
      Serial.println(" segundos de áudio capturados.");
      
      currentState = SENDING;
      break;
    } // Fim do case RECORDING

    case SENDING:
      // O seu case SENDING que já funciona com client.flush() e delay() continua aqui...
      Serial.println("Estado: ENVIANDO...");
      if (client.connect(serverAddress, serverPort)) {
        Serial.println("Conectado ao servidor para envio.");
        client.write(audioBuffer, recordedAudioSize);
        Serial.println("Aguardando finalização do envio (flush)...");
        client.flush(); 
        delay(200); 
        Serial.println("Envio concluído. Fechando conexão.");
        client.stop();
      } else {
        Serial.println("Falha ao conectar ao servidor para envio.");
      }
      
      recordedAudioSize = 0;
      currentState = IDLE;
      Serial.println("\nEstado: AGUARDANDO. Pressione o botão para gravar.");
      delay(500);
      break;
  }
}