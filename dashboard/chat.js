(() => {
    const formulario = document.querySelector("#form-chat");
    const campo = document.querySelector("#mensagem-chat");
    const enviar = document.querySelector("#enviar-chat");
    const reiniciar = document.querySelector("#nova-conversa");
    const conversa = document.querySelector("#conversa");
    const estado = document.querySelector("#estado-chat");
    const endereco = `${location.protocol}//${location.hostname}:8090/chat`;
    let sessao = null;

    function exibir(autor, texto, usuario = false) {
        const item = document.createElement("article");
        item.className = usuario ? "mensagem-chat usuario" : "mensagem-chat";
        const nome = document.createElement("strong");
        const mensagem = document.createElement("p");
        nome.textContent = autor;
        mensagem.textContent = texto;
        item.append(nome, mensagem);
        conversa.append(item);
        conversa.scrollTop = conversa.scrollHeight;
    }

    reiniciar.addEventListener("click", () => {
        sessao = null;
        conversa.replaceChildren();
        estado.textContent = "Nova conversa iniciada.";
        campo.value = "";
        campo.focus();
    });

    formulario.addEventListener("submit", async (evento) => {
        evento.preventDefault();
        const mensagem = campo.value.trim();
        if (!mensagem || enviar.disabled) return;
        campo.disabled = enviar.disabled = reiniciar.disabled = true;
        estado.textContent = "Consultando o assistente…";
        try {
            const resposta = await fetch(endereco, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({mensagem, sessao}),
                signal: AbortSignal.timeout(95000),
            });
            const dados = await resposta.json();
            if (!resposta.ok) {
                estado.textContent = dados.erro || "Não foi possível obter uma resposta.";
                return;
            }
            sessao = dados.sessao;
            const doCache = dados.cache === "hit";
            exibir("Você", mensagem, true);
            exibir(doCache ? "Assistente · Recuperado do cache semântico" : "Assistente", dados.resposta);
            campo.value = "";
            if (doCache) {
                const sim = typeof dados.similaridade === "number"
                    ? ` (similaridade: ${(dados.similaridade * 100).toLocaleString("pt-BR", {maximumFractionDigits: 1})}%)`
                    : "";
                estado.textContent = `Resposta recuperada do cache semântico${sim} · Julgador não acionado.`;
            } else if (dados.avaliacao) {
                const situacao = dados.avaliacao.estado === "aprovado" ? "Aprovada"
                    : dados.avaliacao.estado === "reprovado" ? "Reprovada" : "Sem notas válidas";
                const sufixoCache = dados.cache === "miss" ? " e adicionada ao cache semântico" : "";
                estado.textContent = `Conversa avaliada pelo julgador (${situacao})${sufixoCache}. Consulte a aba Notas do julgador.`;
            } else {
                estado.textContent = "";
            }
        } catch {
            estado.textContent = "O assistente não respondeu. Confira se o serviço está iniciado e tente novamente.";
        } finally {
            campo.disabled = enviar.disabled = reiniciar.disabled = false;
            campo.focus();
        }
    });
})();
