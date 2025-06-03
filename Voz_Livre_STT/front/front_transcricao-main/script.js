// No seu script.js ou dentro da tag <script>

const startBtn = document.getElementById('startBtn');
const logDisplayBox = document.getElementById('logDisplayBox');     // Para exibir a transcrição/logs do servidor
const statusDiv = document.getElementById('transcription');         // Para exibir mensagens de status da interface/conexão

let isTranscriptionActive = false;

// Certifique-se de que o endereço e a porta estão corretos para o seu servidor Python WebSocket
const socket = new WebSocket('ws://localhost:8765'); 

socket.onopen = () => {
    statusDiv.innerText = "Conectado. Clique em 'Iniciar Transcrição'."; // Mensagem de status
    logDisplayBox.innerHTML = ""; // Limpa a caixa de transcrição/log principal
    startBtn.disabled = false;
    startBtn.innerText = "Iniciar Transcrição";
    console.log("WebSocket conectado!");
};

socket.onmessage = (event) => {
    const messageFromServer = event.data; // Esta é a mensagem vinda do servidor Python
    console.log("Mensagem do servidor recebida:", messageFromServer);

    if (isTranscriptionActive) {
        // Todas as mensagens recebidas do servidor enquanto ativo vão para logDisplayBox
        logDisplayBox.innerHTML += messageFromServer + "<br>";
        logDisplayBox.scrollTop = logDisplayBox.scrollHeight; // Auto-scroll
        // statusDiv pode continuar mostrando "Ouvindo / Transcrevendo..." ou ser atualizado se necessário
    } else {
        // Se não estiver ativo, apenas loga no console do navegador, não atualiza a UI principal
        console.log("(Visualização pausada na UI) Mensagem do servidor:", messageFromServer);
    }
};

socket.onerror = (error) => {
    console.error('Erro no WebSocket:', error);
    if (statusDiv) {
        statusDiv.innerText = "Erro na conexão com o servidor.";
    }
    // Você pode decidir se quer mostrar o erro também no logDisplayBox
    // if (logDisplayBox) {
    //     logDisplayBox.innerHTML += "<strong>Erro na conexão com o WebSocket.</strong><br>";
    //     logDisplayBox.scrollTop = logDisplayBox.scrollHeight;
    // }
    startBtn.disabled = true;
};

socket.onclose = () => {
    console.log("WebSocket desconectado.");
    if (statusDiv) {
        statusDiv.innerText = "Desconectado. Tente recarregar a página.";
    }
    // Opcional: adicionar uma mensagem ao logDisplayBox sobre a desconexão
    // if (logDisplayBox && logDisplayBox.innerHTML !== "") { // Adiciona apenas se já havia algo
    //     logDisplayBox.innerHTML += "--- Conexão WebSocket Fechada ---<br>";
    //     logDisplayBox.scrollTop = logDisplayBox.scrollHeight;
    // }
    startBtn.disabled = true;
    isTranscriptionActive = false;
    startBtn.innerText = "Iniciar Transcrição";
};

startBtn.addEventListener('click', () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        if (statusDiv) {
            statusDiv.innerText = "Aguardando conexão com o servidor...";
        }
        return;
    }

    if (isTranscriptionActive) {
        // Pausando a visualização
        socket.send("PAUSAR_TRANSCRICAO"); // Informa o servidor (se ele precisar saber)
        isTranscriptionActive = false;
        startBtn.innerText = "Iniciar Transcrição";
        if (statusDiv) {
            statusDiv.innerText = "Visualização pausada. Clique para iniciar.";
        }
        if (logDisplayBox) { // Adiciona um separador no log principal ao pausar
            logDisplayBox.innerHTML += "--- Visualização de Logs/Transcrições Pausada ---<br>";
            logDisplayBox.scrollTop = logDisplayBox.scrollHeight;
        }
        console.log("Solicitação de PAUSA para visualização enviada.");
    } else {
        // Iniciando a visualização
        if (logDisplayBox) { 
            logDisplayBox.innerHTML = ""; // Limpa o logDisplayBox ao (re)iniciar
            logDisplayBox.innerHTML += "--- Aguardando logs/transcrições do servidor ---<br>";
        }
        if (statusDiv) {
            statusDiv.innerText = "Ouvindo / Visualizando...";
        }
        socket.send("INICIAR_TRANSCRICAO"); // Informa o servidor
        isTranscriptionActive = true;
        startBtn.innerText = "Pausar Transcrição";
        console.log("Solicitação de INÍCIO para visualização enviada.");
    }
});

// Botão inicialmente desabilitado até a conexão WebSocket ser estabelecida
startBtn.disabled = true;