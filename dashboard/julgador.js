(() => {
    const porId = (id) => document.getElementById(id);
    const seletor = porId("relatorio");
    const filtro = porId("filtro");
    const atualizar = porId("atualizar");
    const estado = porId("estado");
    const api = `${location.protocol}//${location.hostname}:8090/julgador/relatorios`;
    const criterios = ["correcao_factual", "aderencia", "justificativa", "clareza", "limites"];
    const rotulos = {aprovado: "Aprovado", reprovado: "Reprovado", sem_notas: "Sem notas válidas"};
    const nomes = {orcamento_quartos: "Orçamento e quartos", bairro: "Bairro", comparacao: "Comparação",
        sem_dados: "Falta de informações", sem_resultado: "Sem opções compatíveis", reservado: "Imóvel reservado",
        alugado: "Imóvel alugado", pedido: "Situação do pedido", avaliacoes: "Avaliações",
        falha_mcp: "Falha do MCP", fora_escopo: "Fora do escopo", instrucao_em_dados: "Instrução nos dados",
        continuidade: "Continuidade da conversa"};
    let relatorio = null;
    let selecionado = null;

    function elemento(tag, texto, classe) {
        const el = document.createElement(tag);
        if (texto !== undefined && texto !== null) el.textContent = String(texto);
        if (classe) el.className = classe;
        return el;
    }

    function data(valor) {
        return new Date(valor).toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short"});
    }

    function nome(caso) { return nomes[caso.id] || caso.id.replaceAll("_", " "); }
    function lista(valor) { return Array.isArray(valor) ? valor : []; }
    function distintivo(caso) { return elemento("span", rotulos[caso.estado], `resultado-caso resultado-${caso.estado}`); }

    async function buscar(url) {
        const resposta = await fetch(url, {signal: AbortSignal.timeout(10000), cache: "no-store"});
        const dados = await resposta.json();
        if (!resposta.ok) throw new Error(dados.erro || "Não foi possível consultar o relatório.");
        return dados;
    }

    function limpar() {
        relatorio = null;
        selecionado = null;
        porId("resultado").hidden = true;
        porId("detalhe").hidden = true;
        porId("metadados").hidden = true;
    }

    function mostrarErro(erro) {
        limpar();
        estado.className = "falha";
        estado.textContent = erro instanceof TypeError || erro.name === "TimeoutError"
            ? "Não foi possível consultar o julgador. Confira se o serviço especialista está iniciado e tente atualizar."
            : erro.message || "Não foi possível carregar o relatório.";
    }

    function mostrarRelatorio(dados) {
        relatorio = dados;
        filtro.value = "todos";
        porId("total").textContent = dados.total;
        porId("aprovados").textContent = dados.aprovado;
        porId("reprovados").textContent = dados.reprovado;
        porId("sem-notas").textContent = dados.sem_notas;
        const metadados = porId("metadados");
        metadados.replaceChildren();
        for (const [titulo, valor] of [
            ["Execução (horário de Brasília)", data(dados.data_utc)],
            ["Modelo do assistente", dados.modelo_assistente], ["Modelo do juiz", dados.modelo_juiz],
            ["Provedor do assistente", dados.provedor || "Não informado"],
            ["Provedor do juiz", dados.provedor_juiz || "Não informado"],
            ["Cache na avaliação", dados.cache === false ? "Desativado" : dados.cache === true ? "Ativado" : "Não informado"],
            ["Arquivo", dados.arquivo],
        ]) {
            const bloco = elemento("div");
            bloco.append(elemento("dt", titulo), elemento("dd", valor));
            metadados.append(bloco);
        }
        metadados.hidden = false;
        porId("resultado").hidden = false;
        estado.className = "conectado";
        estado.textContent = "Relatório carregado. Nenhuma nova avaliação foi executada.";
        mostrarTabela();
    }

    function mostrarTabela() {
        if (!relatorio) return;
        const casos = relatorio.resultados.filter(c => filtro.value === "todos" || c.estado === filtro.value);
        const corpo = porId("casos");
        corpo.replaceChildren();
        porId("contagem").textContent = `${casos.length} de ${relatorio.total} casos exibidos · ${relatorio.total - relatorio.sem_notas} pareceres com notas válidas na rodada.`;
        if (!casos.some(c => c.id === selecionado)) porId("detalhe").hidden = true;
        if (!casos.length) {
            const linha = elemento("tr");
            const celula = elemento("td", "Nenhum caso neste filtro.");
            celula.colSpan = 8;
            linha.append(celula);
            corpo.append(linha);
        }
        for (const caso of casos) {
            const linha = elemento("tr");
            if (caso.id === selecionado) linha.classList.add("selecionado");
            const titulo = elemento("th", nome(caso));
            titulo.scope = "row";
            linha.append(titulo);
            for (const criterio of criterios) linha.append(elemento("td", caso.julgamento?.notas[criterio] ?? "—", "nota"));
            const situacao = elemento("td");
            situacao.append(distintivo(caso));
            const acao = elemento("td");
            const botao = elemento("button", "Ver detalhes", "ver-caso");
            botao.type = "button";
            botao.setAttribute("aria-label", `Ver detalhes: ${nome(caso)}`);
            botao.setAttribute("aria-controls", "detalhe");
            botao.addEventListener("click", () => mostrarCaso(caso));
            acao.append(botao);
            linha.append(situacao, acao);
            corpo.append(linha);
        }
    }

    function mostrarLista(id, itens, vazio) {
        const destino = porId(id);
        destino.replaceChildren();
        if (!lista(itens).length) return destino.append(elemento("p", vazio));
        const ul = elemento("ul");
        for (const item of itens) ul.append(elemento("li", item));
        destino.append(ul);
    }

    function mostrarCaso(caso) {
        selecionado = caso.id;
        mostrarTabela();
        porId("titulo-caso").textContent = nome(caso);
        porId("situacao-caso").replaceChildren(distintivo(caso));
        const fontes = {mcp: "Ferramentas MCP reais", chat_web: "Conversa no chat web", falha: "Ferramenta simulada: indisponibilidade", injecao: "Ferramenta simulada: instrução maliciosa"};
        porId("fonte-caso").textContent = `${caso.id} · ${fontes[caso.fonte] || "Fonte não informada"}`;
        const falha = porId("falha-caso");
        falha.hidden = caso.estado !== "sem_notas";
        falha.textContent = `Esta avaliação não produziu notas válidas.${caso.falha ? ` Falha registrada: ${caso.falha}.` : " O parecer está ausente ou inválido."} Isso não equivale a nota zero.`;
        porId("parecer").textContent = caso.julgamento?.justificativa || "Não há justificativa validada do juiz para este caso.";
        mostrarLista("erros", caso.erros_objetivos, lista(caso.turnos).length ? "Nenhum erro objetivo registrado." : "Não há verificações registradas para este caso.");
        mostrarLista("sem-suporte", caso.julgamento?.sem_suporte, caso.julgamento ? "Nenhuma afirmação sem suporte apontada pelo juiz." : "Sem parecer válido para verificar este item.");
        porId("referencia").textContent = caso.referencia || "Referência não informada.";
        const turnos = porId("turnos");
        turnos.replaceChildren();
        if (!lista(caso.turnos).length) turnos.append(elemento("p", "Nenhuma resposta foi registrada antes da falha."));
        for (const [indice, turno] of lista(caso.turnos).entries()) {
            if (!turno || typeof turno !== "object") continue;
            const bloco = elemento("article", null, "turno");
            bloco.append(elemento("strong", `Pergunta ${indice + 1}`), elemento("p", turno.pergunta || "Não registrada."),
                elemento("strong", "Resposta do assistente"), elemento("p", turno.resposta || "Não registrada."));
            if (Number.isFinite(turno.latencia_ms)) bloco.append(elemento("p", `Tempo da inferência: ${turno.latencia_ms.toLocaleString("pt-BR")} ms`, "legenda"));
            const evidencias = lista(turno.evidencias);
            const detalhe = elemento("details");
            detalhe.append(elemento("summary", `Evidências MCP (${evidencias.length} ${evidencias.length === 1 ? "consulta" : "consultas"})`));
            detalhe.append(elemento("pre", evidencias.length ? JSON.stringify(evidencias, null, 2) : "Nenhuma ferramenta foi consultada neste turno."));
            bloco.append(detalhe);
            turnos.append(bloco);
        }
        porId("detalhe").hidden = false;
        porId("titulo-caso").focus({preventScroll: true});
        porId("detalhe").scrollIntoView({block: "start"});
    }

    async function carregar(atualizarLista) {
        const anterior = seletor.value;
        atualizar.disabled = seletor.disabled = true;
        limpar();
        estado.className = "";
        estado.textContent = "Carregando relatório…";
        try {
            if (atualizarLista) {
                const dados = await buscar(api);
                seletor.replaceChildren();
                for (const item of dados.relatorios) {
                    const opcao = elemento("option", `${data(item.data_utc)} · ${item.total} casos · ${item.arquivo}`);
                    opcao.value = item.arquivo;
                    seletor.append(opcao);
                }
                if (dados.relatorios.some(r => r.arquivo === anterior)) seletor.value = anterior;
                if (!dados.relatorios.length) {
                    const vazia = elemento("option", "Nenhum relatório disponível");
                    vazia.value = "";
                    seletor.append(vazia);
                    estado.textContent = "Ainda não há relatórios válidos do julgador. Execute uma avaliação pelo terminal e depois atualize esta página.";
                    return;
                }
            }
            mostrarRelatorio(await buscar(`${api}/${encodeURIComponent(seletor.value)}`));
        } catch (erro) {
            mostrarErro(erro);
        } finally {
            atualizar.disabled = false;
            seletor.disabled = !seletor.value;
        }
    }

    atualizar.addEventListener("click", () => carregar(true));
    seletor.addEventListener("change", () => carregar(false));
    filtro.addEventListener("change", mostrarTabela);
    carregar(true);
})();
