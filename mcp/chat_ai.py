import asyncio
import logging
import os
import json
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv
from openai import AsyncOpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
PROVEDOR = os.getenv("PROVEDOR_IA", "openai").strip().lower()
MODELO = os.getenv("MODELO_IA", "").strip()
PROVEDORES = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4.1-mini"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_API_KEY", "gemini-flash-latest"),
    "claude": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
}


def configurar_ia(*, provedor=None, modelo=None, url=None, chave=None):
    provedor = PROVEDOR if provedor is None else provedor
    modelo = MODELO if modelo is None else modelo
    if provedor == "outro":
        url = os.getenv("URL_IA", "").strip() if url is None else url.strip()
        partes = urlsplit(url)
        local = partes.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        if (not partes.hostname or partes.username or partes.password or partes.query or partes.fragment
                or not (partes.scheme == "https" or partes.scheme == "http" and local)):
            raise ValueError("Use uma URL HTTPS de API compatível, ou HTTP em localhost/host.docker.internal para modelos locais.")
        nome_chave, modelo_padrao = "CHAVE_API_IA", ""
    elif provedor in PROVEDORES:
        url, nome_chave, modelo_padrao = PROVEDORES[provedor]
    else:
        raise ValueError("PROVEDOR_IA deve ser openai, google, claude ou outro.")
    chave = os.getenv(nome_chave, "").strip() if chave is None else chave.strip()
    modelo = modelo or modelo_padrao
    if not chave or chave == "coloque_sua_chave_aqui":
        raise ValueError(f"Preencha {nome_chave} no arquivo .env.")
    if not modelo:
        raise ValueError("Preencha MODELO_IA no arquivo .env.")
    return url, chave, modelo


def configurar_juiz():
    provedor = os.getenv("PROVEDOR_JUIZ", "").strip().lower()
    modelo = os.getenv("MODELO_JUIZ", "").strip()
    url = os.getenv("URL_JUIZ", "").strip()
    chave = os.getenv("CHAVE_API_JUIZ", "").strip()
    if not provedor:
        if url or chave:
            raise ValueError("Defina PROVEDOR_JUIZ ao informar URL_JUIZ ou CHAVE_API_JUIZ.")
        return configurar_ia(modelo=modelo or MODELO)
    if provedor != "outro" and url:
        raise ValueError("URL_JUIZ exige PROVEDOR_JUIZ=outro.")
    # Um endpoint independente não herda acidentalmente a chave do servidor do chat.
    return configurar_ia(provedor=provedor, modelo=modelo, url=url,
                         chave=chave if provedor == "outro" else chave or None)

SERVICOS_MCP = {
    "imoveis": os.getenv("MCP_IMOVEIS", "http://localhost:8001/mcp"),
    "pedidos": os.getenv("MCP_PEDIDOS", "http://localhost:8002/mcp"),
    "avaliacoes": os.getenv("MCP_AVALIACOES", "http://localhost:8003/mcp"),
}
PROMPT = Path(__file__).with_name("conhecimento.md").read_text(encoding="utf-8")
LIMITE_MENSAGEM = 1500
LIMITE_TURNO = 90


async def conectar_servicos(pilha, tolerar_falhas=False):
    servicos = []
    for nome, url in SERVICOS_MCP.items():
        try:
            async with AsyncExitStack() as conexoes:
                leitura, escrita, _ = await conexoes.enter_async_context(streamablehttp_client(url))
                conexao = await conexoes.enter_async_context(ClientSession(leitura, escrita))
                await asyncio.wait_for(conexao.initialize(), timeout=5)
                pilha.push_async_callback(conexoes.pop_all().aclose)
                servicos.append(conexao)
        except Exception:
            if not tolerar_falhas:
                raise
            print(f"MCP indisponível: {nome}")
    return servicos


async def get_ferramentas(servicos):
    ferramentas = {}
    for conexao in servicos:
        try:
            resultado = await asyncio.wait_for(conexao.list_tools(), timeout=5)
        except Exception:
            print("Não foi possível redescobrir ferramentas MCP.")
            continue
        for ferramenta in resultado.tools:
            ferramentas[ferramenta.name] = {
                "conexao": conexao,
                "declaracao": {"type": "function", "function": {
                    "name": ferramenta.name, "description": ferramenta.description or "",
                    "parameters": ferramenta.inputSchema,
                }},
            }
    return ferramentas


def limitar_historico(historico):
    inicios = [i for i, msg in enumerate(historico) if msg["role"] == "user"]
    if len(inicios) > 6:
        del historico[:inicios[-6]]


def ocultar_cliente(dados):
    if isinstance(dados, dict):
        return {chave: ocultar_cliente(valor) for chave, valor in dados.items() if chave != "cliente"}
    if isinstance(dados, list):
        return [ocultar_cliente(item) for item in dados]
    return dados


async def conversar(cliente_ia, ferramentas, mensagem, historico, modelo, evidencias=None, orientacao=""):
    mensagens = historico + [{"role": "user", "content": mensagem}]
    chamadas_mcp = 0
    for tentativa in range(10):
        resposta = await cliente_ia.chat.completions.create(
            model=modelo,
            messages=[{"role": "system", "content": PROMPT + orientacao}] + mensagens,
            **({"tools": [f["declaracao"] for f in ferramentas.values()]} if ferramentas else {}),
        )
        if not resposta.choices or resposta.choices[0].finish_reason in {"length", "content_filter"}:
            return "A IA não retornou uma resposta. Tente novamente."
        resposta_ia = resposta.choices[0].message
        # Preserva também os campos extras enviados pelo provedor (como assinaturas do Google).
        mensagens.append(resposta_ia.model_dump(exclude_none=True))
        if not resposta_ia.tool_calls:
            if not resposta_ia.content or not resposta_ia.content.strip():
                return "Não foi possível gerar uma resposta."
            historico[:] = mensagens
            limitar_historico(historico)
            return resposta_ia.content
        for chamada in resposta_ia.tool_calls:
            chamadas_mcp += 1
            if chamadas_mcp > 12:
                return "A consulta atingiu o limite de chamadas MCP. Faça uma pergunta mais específica."
            argumentos = None
            try:
                argumentos = json.loads(chamada.function.arguments or "{}")
                if not isinstance(argumentos, dict):
                    raise ValueError("Os argumentos precisam ser um objeto JSON.")
                conexao = ferramentas[chamada.function.name]["conexao"]
                resultado = await asyncio.wait_for(
                    conexao.call_tool(chamada.function.name, arguments=argumentos), timeout=8
                )
                dados = [ocultar_cliente(json.loads(parte.text)) for parte in resultado.content if hasattr(parte, "text")]
                falha = resultado.isError or any(isinstance(item, dict) and item.get("erro") for item in dados)
                conteudo = {"erro": bool(falha), "dados": dados}
            except Exception:
                conteudo = {"erro": "Não foi possível consultar a ferramenta. Não invente informações."}
            if evidencias is not None:
                evidencias.append({"ferramenta": chamada.function.name, "argumentos": argumentos, **conteudo})
            mensagens.append({"role": "tool", "tool_call_id": chamada.id,
                              "content": json.dumps(conteudo, ensure_ascii=False)})
    return "A consulta atingiu o limite de dez etapas. Faça uma pergunta mais específica."


async def executar():
    from especialista import responder

    logging.basicConfig(level=logging.INFO)
    try:
        url, chave, modelo = configurar_ia()
    except ValueError as erro:
        print(erro)
        return
    async with AsyncOpenAI(api_key=chave, base_url=url, timeout=25, max_retries=0) as cliente_ia:
        historico = []
        print(f"Locação Residencial v2 — {PROVEDOR}: {modelo}. Digite sair para encerrar.")
        while True:
            mensagem = (await asyncio.to_thread(input, "\nVocê: ")).strip()
            if mensagem.lower() in ["sair", "/s"]:
                break
            if not mensagem:
                continue
            if len(mensagem) > LIMITE_MENSAGEM:
                print(f"Escreva uma mensagem de até {LIMITE_MENSAGEM} caracteres.")
                continue
            try:
                resposta = await responder(cliente_ia, mensagem, historico, modelo)
                print("Assistente:", resposta["resposta"])
            except Exception:
                print("Falha na consulta. Verifique a chave, a cota da IA e os serviços; tente novamente.")


if __name__ == "__main__":
    try:
        asyncio.run(executar())
    except (KeyboardInterrupt, EOFError):
        print("\nChat encerrado.")
