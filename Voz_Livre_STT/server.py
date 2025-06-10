import socket
import pyaudio
import speech_recognition as sr
import threading
import queue
import asyncio
import websockets
import time

# --- 1. Configurações Globais ---
# Rede
TCP_IP = "0.0.0.0"          # Escutar em todas as interfaces de rede
TCP_PORT = 12345            # Porta para o ESP32 se conectar
WEBSOCKET_IP = "0.0.0.0"
WEBSOCKET_PORT = 8765       # Porta para a página web se conectar

# Áudio
RATE = 8000                 # Taxa de amostragem (DEVE ser igual à do ESP32)
FORMAT = pyaudio.paUInt8    # Formato do áudio (8-bit sem sinal)
CHANNELS = 1                # Mono
CHUNK_SIZE_PLAYBACK = 1024  # Tamanho do buffer para o playback no PyAudio

# --- 2. Variáveis de Estado Globais ---
# Fila para passar o bloco de áudio completo para a thread de STT
stt_processing_queue = queue.Queue()
# Conjuntos para gerenciar clientes WebSocket
connected_websockets = set()
transcription_subscribers = set()
# Lock para proteger o acesso aos sets por múltiplas threads
clients_lock = threading.Lock()
# Objeto de reconhecimento de fala
recognizer = sr.Recognizer()

# --- 3. Definições de Funções ---

async def send_to_subscribers(text_message):
    """Envia uma mensagem para todos os clientes WebSocket inscritos."""
    if transcription_subscribers:
        with clients_lock:
            # Cria uma cópia para evitar problemas se o set for modificado durante a iteração
            subscribers_copy = list(transcription_subscribers)
        if subscribers_copy:
            # websockets.broadcast envia para uma lista de conexões de forma eficiente
            websockets.broadcast(subscribers_copy, text_message)
            print(f"WebSocket: Mensagem enviada para {len(subscribers_copy)} inscritos.")

def stt_worker(loop):
    """
    Thread que realiza o Speech-to-Text e envia APENAS o resultado final
    bem-sucedido para os clientes WebSocket.
    """
    print("Thread STT: Iniciada e pronta.")
    while True:
        try:
            full_audio_bytes = stt_processing_queue.get(block=True)
            if full_audio_bytes is None: break

            audio_segment = sr.AudioData(full_audio_bytes, RATE, 1)
            
            # 1. Imprime o status no console do servidor para depuração
            print("Servidor STT: Tentando reconhecer áudio...")
            # A linha abaixo que enviava o status para a web foi REMOVIDA.
            
            try:
                # 2. Tenta reconhecer o texto
                text = recognizer.recognize_google(audio_segment, language='pt-BR')
                
                # 3. Se o reconhecimento for bem-sucedido e gerar um texto:
                print(f"Thread STT - Texto Reconhecido: {text}")
                
                # ENVIA APENAS O TEXTO PURO E RECONHECIDO PARA A PÁGINA WEB
                if text: 
                    # Cria a mensagem final, que pode ser só o texto ou um prefixo
                    # final_message = f"Transcrição: {text}"
                    final_message = text # Enviando apenas o texto puro
                    asyncio.run_coroutine_threadsafe(send_to_subscribers(final_message), loop)

            except sr.UnknownValueError:
                # Se o Google não entender, apenas imprime no console do servidor. NADA é enviado para a web.
                print("Thread STT: Google não entendeu o áudio.")
            except sr.RequestError as e:
                # Se houver um erro de API, apenas imprime no console do servidor. NADA é enviado para a web.
                print(f"Thread STT: Erro na API do Google - {e}")
            finally:
                stt_processing_queue.task_done()
        except Exception as e:
            print(f"Erro na thread STT: {e}")
    print("Thread STT: Finalizada.")

def tcp_walkie_talkie_handler(conn, addr, audio_stream):
    """Recebe um bloco completo de áudio de uma conexão TCP, toca e enfileira para STT."""
    print(f"Thread TCP: Conexão de {addr} estabelecida, aguardando dados...")
    
    all_data = bytearray()
    
    try:
        while True:
            # Recebe dados em pedaços (chunks) até a conexão ser fechada pelo ESP32
            data = conn.recv(4096)
            if not data:
                break # Sai do loop quando o ESP32 fechar a conexão
            all_data.extend(data)

        print(f"Thread TCP: Transmissão de {addr} finalizada. Total de bytes recebidos: {len(all_data)}")
        
        if all_data:

            # --- PLAYBACK DE ÁUDIO DESATIVADO ---
            # Toca o áudio recebido
            #print("Reproduzindo áudio recebido...")
            #if audio_stream and audio_stream.is_active():
            #    audio_stream.write(bytes(all_data))


            # Envia o bloco de áudio completo para a thread de STT
            print("Enviando áudio para transcrição...")
            stt_processing_queue.put(bytes(all_data))

    except Exception as e:
        print(f"Thread TCP: Erro na conexão {addr}: {e}")
    finally:
        conn.close()
        print(f"Thread TCP: Conexão com {addr} fechada.")


def tcp_server_loop(audio_stream):
    """Loop principal que aceita conexões TCP do ESP32."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
        tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_sock.bind((TCP_IP, TCP_PORT))
        tcp_sock.listen()
        print(f"Servidor TCP (modo Walkie-Talkie) escutando em {TCP_IP}:{TCP_PORT}")
        while True:
            try:
                conn, addr = tcp_sock.accept()
                # Inicia uma nova thread para lidar com este cliente
                client_handler_thread = threading.Thread(
                    target=tcp_walkie_talkie_handler, 
                    args=(conn, addr, audio_stream), 
                    daemon=True
                )
                client_handler_thread.start()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Servidor TCP: Erro ao aceitar conexão: {e}")
                break
    print("Servidor TCP: Finalizado.")


async def websocket_handler(websocket):
    """Lida com cada conexão WebSocket da página web."""
    try:
        path = websocket.path
    except AttributeError:
        path = "N/A"
        
    print(f"WebSocket: Cliente {websocket.remote_address} conectado ao path '{path}'.")
    with clients_lock:
        connected_websockets.add(websocket)
    try:
        await websocket.send("Servidor: Conectado! Pressione o botão no dispositivo para gravar e enviar.")
        async for message in websocket:
            print(f"WebSocket: Recebido de {websocket.remote_address}: {message}")
            if message == "INICIAR_TRANSCRICAO":
                with clients_lock:
                    transcription_subscribers.add(websocket)
                await websocket.send("Servidor: Visualização ATIVADA.")
            elif message == "PAUSAR_TRANSCRICAO":
                with clients_lock:
                    transcription_subscribers.discard(websocket)
                await websocket.send("Servidor: Visualização PAUSADA.")
    except websockets.exceptions.ConnectionClosed:
        print(f"WebSocket: Cliente {websocket.remote_address} desconectou.")
    finally:
        with clients_lock:
            transcription_subscribers.discard(websocket)
            connected_websockets.discard(websocket)

async def main():
    """Função principal que inicia todos os servidores e threads."""


    # --- PLAYBACK DE ÁUDIO DESATIVADO ---
    #p = pyaudio.PyAudio()
    #audio_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK_SIZE_PLAYBACK)
    

    audio_stream = None

    # Pega o event loop atual para passar para a thread STT
    loop = asyncio.get_running_loop()

    # Inicia as threads
    threading.Thread(target=stt_worker, args=(loop,), daemon=True).start()
    threading.Thread(target=tcp_server_loop, args=(audio_stream,), daemon=True).start()

    # Inicia o servidor WebSocket e o mantém rodando
    async with websockets.serve(websocket_handler, WEBSOCKET_IP, WEBSOCKET_PORT):
        print(f"Servidor WebSocket escutando em ws://{WEBSOCKET_IP}:{WEBSOCKET_PORT}")
        await asyncio.Future()  # Roda indefinidamente

# --- 4. Bloco de Execução Principal ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nPrograma principal interrompido.")
    finally:
        print("Finalizando...")
        # A limpeza de recursos como PyAudio poderia ser feita aqui, 
        # mas como as threads são 'daemon', elas fecharão com o programa principal.