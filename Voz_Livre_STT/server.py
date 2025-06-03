import socket
import pyaudio
import speech_recognition as sr
import threading
import queue
import asyncio
import websockets
import json # Usaremos para mensagens mais estruturadas, se necessário

# --- Configurações do Servidor UDP ---
UDP_IP = "0.0.0.0"
UDP_PORT = 12345

# --- Configurações de Áudio (devem corresponder ao ESP32) ---
FORMAT = pyaudio.paUInt8
CHANNELS = 1
RATE = 8000
CHUNK_SIZE = 128 # Tamanho do buffer de áudio recebido do ESP32

# --- Configurações do Servidor WebSocket ---
WEBSOCKET_IP = "0.0.0.0" # Escutar em todas as interfaces
WEBSOCKET_PORT = 8765

# --- Globais para WebSocket e STT ---
# Mantém o controle de todos os clientes WebSocket conectados
connected_websockets = set()
# Mantém o controle dos clientes que querem receber transcrições
transcription_subscribers = set()

audio_processing_queue = queue.Queue()
recognizer = sr.Recognizer()

# Lock para acesso seguro aos sets de WebSockets por múltiplas threads/tasks
clients_lock = threading.Lock() # Usaremos Lock do threading pois STT worker é uma thread síncrona

# --- Inicializações (PyAudio, Socket UDP) ---
# Estas inicializações foram movidas para a função principal ou para onde são usadas
# para evitar duplicação e garantir que sejam feitas no contexto correto.
p = None
audio_stream = None # Renomeado de 'stream' para evitar conflito com streams de websockets
udp_sock = None


async def send_transcription_to_subscribers(text_message):
    """Envia a mensagem de texto para todos os clientes WebSocket inscritos."""
    # Esta função será chamada pela thread STT usando asyncio.run_coroutine_threadsafe
    # já que a thread STT é síncrona e o envio do WebSocket é assíncrono.
    if transcription_subscribers: # Verifica se há inscritos
        # Cria uma cópia do set para iterar, caso ele seja modificado durante a iteração
        # Embora com o lock, talvez não seja estritamente necessário, é mais seguro.
        current_subscribers = set()
        with clients_lock:
            current_subscribers = transcription_subscribers.copy()
        
        # websockets.broadcast envia para uma lista de conexões
        # Se precisar enviar individualmente com tratamento de erro por cliente:
        # tasks = [ws.send(text_message) for ws in current_subscribers]
        # await asyncio.gather(*tasks, return_exceptions=True) # Envia para todos e lida com exceções
        
        # Simplesmente iterando e enviando (pode ser melhorado com error handling por cliente)
        print(f"WebSocket: Enviando texto '{text_message}' para {len(current_subscribers)} inscritos.")
        for ws_client in current_subscribers:
            try:
                await ws_client.send(text_message)
            except websockets.exceptions.ConnectionClosed:
                print(f"WebSocket: Conexão com {ws_client.remote_address} fechada ao tentar enviar.")
                # Remover o cliente se a conexão foi fechada (será feito no handler principal também)
                pass # O handler principal deve cuidar da remoção
            except Exception as e_ws_send:
                print(f"WebSocket: Erro ao enviar para {ws_client.remote_address}: {e_ws_send}")


def stt_worker(loop_for_async_tasks):
    """Esta função roda em uma thread separada para processar o áudio."""
    global recognizer
    while True:
        try:
            audio_chunk_bytes = audio_processing_queue.get(block=True)
            if audio_chunk_bytes is None:
                print("Thread STT: Recebido sinal para parar.")
                # Enviar mensagem de parada para a web também pode ser útil
                # asyncio.run_coroutine_threadsafe(send_transcription_to_subscribers("Servidor STT: Worker parado."), loop_for_async_tasks)
                break

            audio_segment = sr.AudioData(audio_chunk_bytes, RATE, 1)

            log_msg_stt = "Servidor STT: Tentando reconhecer áudio..."
            print(log_msg_stt)
            asyncio.run_coroutine_threadsafe(send_transcription_to_subscribers(log_msg_stt), loop_for_async_tasks)

            try:
                text = recognizer.recognize_google(audio_segment, language='pt-BR')
                log_msg_stt = f"Servidor STT - Texto Reconhecido: {text}"
                print(log_msg_stt)
                if text: # Somente envia se houver texto
                    asyncio.run_coroutine_threadsafe(send_transcription_to_subscribers(log_msg_stt), loop_for_async_tasks)

            except sr.UnknownValueError:
                log_msg_stt = "Servidor STT: Google não entendeu o áudio."
                print(log_msg_stt)
                asyncio.run_coroutine_threadsafe(send_transcription_to_subscribers(log_msg_stt), loop_for_async_tasks)
            except sr.RequestError as e:
                log_msg_stt = f"Servidor STT: Erro na API do Google; {e}"
                print(log_msg_stt)
                asyncio.run_coroutine_threadsafe(send_transcription_to_subscribers(log_msg_stt), loop_for_async_tasks)
            finally:
                audio_processing_queue.task_done()
        except Exception as e_thread:
            log_msg_stt = f"Servidor STT: Erro na thread - {e_thread}"
            print(log_msg_stt)
            asyncio.run_coroutine_threadsafe(send_transcription_to_subscribers(log_msg_stt), loop_for_async_tasks)
    print("Thread STT: Finalizada.")


async def websocket_handler(websocket):  # <--- IMPORTANTE: APENAS 'websocket' COMO ARGUMENTO AQUI
    """Lida com cada conexão WebSocket do cliente (página web)."""
    global connected_websockets, transcription_subscribers
    
    # Tenta obter o 'path' como um atributo do objeto websocket
    try:
        path = websocket.path 
    except AttributeError:
        path = "N/A (path attribute not found)" # Lida com o caso de não existir o atributo
    
    print(f"WebSocket: Cliente {websocket.remote_address} conectado ao path '{path}'.")
    with clients_lock:
        connected_websockets.add(websocket)
    
    try:
        async for message in websocket:
            print(f"WebSocket: Recebido de {websocket.remote_address} (path: {path}): {message}")
            if message == "INICIAR_TRANSCRICAO":
                with clients_lock:
                    transcription_subscribers.add(websocket)
                print(f"WebSocket: Cliente {websocket.remote_address} INSCREVEU-SE para transcrições.")
            elif message == "PAUSAR_TRANSCRICAO":
                with clients_lock:
                    transcription_subscribers.discard(websocket)
                print(f"WebSocket: Cliente {websocket.remote_address} CANCELOU INSCRIÇÃO para transcrições.")
            else:
                print(f"WebSocket: Mensagem desconhecida de {websocket.remote_address}: {message}")
    except websockets.exceptions.ConnectionClosedOK:
        print(f"WebSocket: Cliente {websocket.remote_address} (path: {path}) desconectou normalmente.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"WebSocket: Cliente {websocket.remote_address} (path: {path}) desconectou com erro: {e}")
    except Exception as e_ws_handler:
        print(f"WebSocket: Erro no handler para {websocket.remote_address} (path: {path}): {e_ws_handler}")
    finally:
        print(f"WebSocket: Finalizando conexão com {websocket.remote_address} (path: {path}).")
        with clients_lock:
            connected_websockets.discard(websocket)
            transcription_subscribers.discard(websocket)


def udp_audio_receiver_and_player_loop():
    """Loop síncrono para receber áudio UDP e tocar/enfileirar para STT."""
    global p, audio_stream, udp_sock # Acessa as globais
    
    # Buffer para acumular áudio para STT
    stt_buffer_target_size = RATE * 1 * 3 # Acumula 3 segundos de áudio (8000 * 1 byte/amostra * 3s)
    accumulated_audio_for_stt = bytearray()

    print("Thread UDP/Player: Iniciando...")
    while True: # Adicione uma condição de parada se necessário (ex: uma flag global)
        try:
            data, addr = udp_sock.recvfrom(CHUNK_SIZE)
            
            if audio_stream and audio_stream.is_active():
                audio_stream.write(data)
            
            accumulated_audio_for_stt.extend(data)
            
            if len(accumulated_audio_for_stt) >= stt_buffer_target_size:
                audio_processing_queue.put(bytes(accumulated_audio_for_stt))
                accumulated_audio_for_stt.clear()
        except socket.timeout: # Adicionado para não bloquear para sempre no recvfrom
            continue 
        except Exception as e_udp_loop:
            print(f"Erro no loop UDP/Player: {e_udp_loop}")
            # Se houver um erro crítico, pode ser necessário quebrar o loop
            # ou tentar reiniciar o socket/stream, dependendo do erro.
            # Por agora, apenas imprime e continua.
            # Se o socket fechar, este loop vai quebrar.
            break 
    print("Thread UDP/Player: Finalizada.")


async def main():
    """Função principal para iniciar todos os servidores e threads."""
    global p, audio_stream, udp_sock # Modifica as globais
    
    # --- Inicializações (PyAudio, Socket UDP) ---
    # Colocadas aqui para serem inicializadas antes de qualquer uso.
    p = pyaudio.PyAudio()
    audio_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK_SIZE)
    
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind((UDP_IP, UDP_PORT))
    udp_sock.settimeout(1.0) # Adiciona um timeout ao recvfrom para não bloquear indefinidamente

    print(f"Servidor UDP escutando em {UDP_IP}:{UDP_PORT}")
    print(f"Stream de áudio configurado para {RATE}Hz, formato {FORMAT}")

    # Pega o event loop atual para passar para a thread STT (para run_coroutine_threadsafe)
    loop = asyncio.get_event_loop()

    # Inicia a thread do worker STT
    stt_thread = threading.Thread(target=stt_worker, args=(loop,), daemon=True)
    stt_thread.start()

    # Inicia o loop de recebimento de áudio UDP em uma thread separada
    # Isso é necessário porque o servidor WebSocket (asyncio) bloqueará a thread principal.
    udp_thread = threading.Thread(target=udp_audio_receiver_and_player_loop, daemon=True)
    udp_thread.start()

    # Inicia o servidor WebSocket
    # Use um bloco try/except para o start_server para capturar KeyboardInterrupt ali também
    server_instance = None
    try:
        print(f"Servidor WebSocket escutando em ws://{WEBSOCKET_IP}:{WEBSOCKET_PORT}")
        async with websockets.serve(websocket_handler, WEBSOCKET_IP, WEBSOCKET_PORT) as ws_server:
            server_instance = ws_server # Guarda a instância para referência, se necessário
            await asyncio.Future()  # Mantém o servidor rodando indefinidamente até ser interrompido
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt recebido no main, fechando WebSocket server...")
    except Exception as e_main_ws:
        print(f"Erro ao iniciar/rodar servidor WebSocket: {e_main_ws}")
    finally:
        print("Main: Sinalizando para threads pararem...")
        audio_processing_queue.put(None) # Envia sinal para a thread STT parar
        
        # Para parar a thread UDP, você precisaria de uma flag ou fechar o socket de outra thread.
        # Como ela é daemon, ela fechará com o programa principal se o socket der erro ou fechar.
        # Uma forma mais limpa seria ter uma flag `running = True` e setá-la para False aqui.
        if udp_sock:
            print("Main: Fechando socket UDP.")
            udp_sock.close() # Isso deve fazer a thread UDP sair do loop no recvfrom

        if stt_thread.is_alive():
            print("Main: Aguardando thread STT finalizar...")
            stt_thread.join(timeout=5)
        if udp_thread.is_alive():
            print("Main: Aguardando thread UDP/Player finalizar...")
            udp_thread.join(timeout=5) # Espera a thread UDP terminar
        
        if audio_stream and audio_stream.is_active():
            print("Main: Parando e fechando stream PyAudio.")
            audio_stream.stop_stream()
        if audio_stream:
            audio_stream.close()
        if p:
            print("Main: Terminando PyAudio.")
            p.terminate()
        
        print("Main: Recursos liberados. Servidor finalizado.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Programa principal interrompido.")
    except Exception as e_global:
        print(f"Erro global não tratado: {e_global}")