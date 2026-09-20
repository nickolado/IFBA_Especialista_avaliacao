const API = {
    imoveis: "http://localhost:7001/imoveis",
    pedidos: "http://localhost:7002/pedidos",
    avaliacoes: "http://localhost:7003/avaliacoes"
};
const carregando = {};
const nomes = { disponivel: "Disponível", reservado: "Reservado", alugado: "Alugado",
    pendente: "Pendente", aprovado: "Aprovado", recusado: "Recusado", cancelado: "Cancelado", concluido: "Concluído" };

async function acessar(url, metodo = "GET", dados) {
    const controle = new AbortController();
    const limite = setTimeout(() => controle.abort(), 6000);
    try {
        const resposta = await fetch(url, {
            method: metodo, signal: controle.signal, cache: "no-store",
            headers: dados ? { "Content-Type": "application/json" } : {},
            body: dados ? JSON.stringify(dados) : undefined
        });
        const conteudo = await resposta.json();
        if (!resposta.ok) throw new Error(conteudo.erro || "Falha na consulta.");
        return conteudo;
    } catch (erro) {
        if (erro.name === "AbortError" || erro instanceof TypeError) {
            throw new Error("Serviço indisponível. Tente novamente em instantes.");
        }
        throw erro;
    } finally {
        clearTimeout(limite);
    }
}

function mostrar_tabela(area, titulos, linhas) {
    const caixa = document.getElementById("lista-" + area);
    caixa.replaceChildren();
    if (!linhas.length) {
        caixa.textContent = "Nenhum registro encontrado.";
        return null;
    }
    const tabela = document.createElement("table");
    const cabecalho = tabela.createTHead().insertRow();
    for (const titulo of titulos) {
        const coluna = document.createElement("th");
        coluna.scope = "col";
        coluna.textContent = titulo;
        cabecalho.append(coluna);
    }
    const corpo = tabela.createTBody();
    for (const valores of linhas) {
        const linha = corpo.insertRow();
        for (const valor of valores) {
            const celula = linha.insertCell();
            // textContent exibe nomes e comentários como texto, sem executar HTML.
            if (typeof valor === "object" && valor.situacao) {
                const etiqueta = document.createElement("span");
                etiqueta.className = "situacao " + valor.situacao;
                etiqueta.textContent = nomes[valor.situacao] || valor.situacao;
                celula.append(etiqueta);
            } else {
                celula.textContent = valor;
            }
        }
    }
    caixa.append(tabela);
    return corpo;
}

function mostrar_imoveis(imoveis) {
    document.getElementById("total-imoveis").textContent = imoveis.filter(i => i.situacao === "disponivel").length;
    mostrar_tabela("imoveis", ["Nº", "Descrição", "Bairro", "Tipo", "Quartos", "Aluguel mensal", "Situação"],
        imoveis.map(i => [i.imovel_id, i.descricao, i.bairro, i.tipo, i.quartos,
            Number(i.valor_mensal).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }), { situacao: i.situacao }]));
}

function mostrar_pedidos(pedidos) {
    document.getElementById("total-pedidos").textContent = pedidos.filter(p => p.situacao === "pendente").length;
    const corpo = mostrar_tabela("pedidos", ["Nº", "Cliente", "Imóvel", "Solicitação", "Situação", "Ações"],
        pedidos.map(p => [p.pedido_id, p.cliente, p.imovel_id, new Date(p.data_solicitacao).toLocaleDateString("pt-BR"),
            { situacao: p.situacao }, ""]));
    if (!corpo) return;
    pedidos.forEach((pedido, indice) => {
        const acoes = pedido.situacao === "pendente" ? ["aprovado", "recusado", "cancelado"] :
            pedido.situacao === "aprovado" ? ["concluido", "cancelado"] : [];
        const celula = corpo.rows[indice].lastElementChild;
        celula.className = "acoes";
        const rotulos = { aprovado: "Aprovar", recusado: "Recusar", cancelado: "Cancelar", concluido: "Concluir" };
        for (const situacao of acoes) {
            const botao = document.createElement("button");
            botao.textContent = rotulos[situacao];
            botao.setAttribute("aria-label", rotulos[situacao] + " pedido " + pedido.pedido_id);
            botao.onclick = async () => {
                botao.disabled = true;
                const mensagem = document.getElementById("mensagem-situacao");
                try {
                    await acessar(API.pedidos + "/" + pedido.pedido_id + "/situacao", "PATCH", { situacao });
                    mensagem.textContent = "Pedido " + pedido.pedido_id + " atualizado.";
                    atualizar_tudo();
                } catch (erro) {
                    mensagem.textContent = erro.message;
                } finally {
                    botao.disabled = false;
                }
            };
            celula.append(botao);
        }
        if (!acoes.length) celula.textContent = "Finalizado";
    });
}

function mostrar_avaliacoes(avaliacoes) {
    const media = avaliacoes.length ? (avaliacoes.reduce((soma, a) => soma + a.nota, 0) / avaliacoes.length).toFixed(1) : "—";
    document.getElementById("total-avaliacoes").textContent = media === "—" ? media : media.replace(".", ",");
    mostrar_tabela("avaliacoes", ["Nº", "Pedido", "Imóvel", "Cliente", "Nota", "Comentário"],
        avaliacoes.map(a => [a.avaliacao_id, a.pedido_id, a.imovel_id, a.cliente, a.nota + " / 5", a.comentario]));
}

const exibir = { imoveis: mostrar_imoveis, pedidos: mostrar_pedidos, avaliacoes: mostrar_avaliacoes };
async function atualizar(area) {
    if (carregando[area]) return;
    carregando[area] = true;
    const estado = document.getElementById("estado-" + area);
    try {
        const dados = await acessar(API[area]);
        exibir[area](dados);
        estado.textContent = "Disponível · " + new Date().toLocaleTimeString("pt-BR");
        estado.className = "conectado";
    } catch (erro) {
        estado.textContent = "Indisponível · tentando reconectar automaticamente";
        estado.className = "falha";
        document.getElementById("lista-" + area).textContent = erro.message;
        document.getElementById("total-" + area).textContent = "—";
    } finally {
        carregando[area] = false;
    }
}

function atualizar_tudo() {
    // Cada área tem sua própria consulta e seu próprio tratamento de erro.
    for (const area of Object.keys(API)) atualizar(area);
}

function preparar_formulario(nome, area, campos_numericos) {
    const formulario = document.getElementById("form-" + nome);
    formulario.onsubmit = async evento => {
        evento.preventDefault();
        const dados = Object.fromEntries(new FormData(formulario));
        for (const campo of campos_numericos) dados[campo] = Number(dados[campo]);
        const botao = formulario.querySelector("button");
        const mensagem = document.getElementById("mensagem-" + nome);
        botao.disabled = true;
        try {
            await acessar(API[area], "POST", dados);
            mensagem.textContent = "Registro salvo com sucesso.";
            formulario.reset();
            atualizar_tudo();
        } catch (erro) {
            mensagem.textContent = erro.message;
        } finally {
            botao.disabled = false;
        }
    };
}

preparar_formulario("imovel", "imoveis", ["quartos", "valor_mensal"]);
preparar_formulario("pedido", "pedidos", ["imovel_id"]);
preparar_formulario("avaliacao", "avaliacoes", ["pedido_id", "nota"]);
atualizar_tudo();
setInterval(atualizar_tudo, 5000);
