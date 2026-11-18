import asyncio
import logging
import os
import sqlite3
from contextlib import AsyncExitStack
from time import perf_counter

from openai import APIError
from cache_semantico import ORIENTACOES, configurar_cache, elegivel_dinamico, identificar_topico, normalizar
from chat_ai import LIMITE_TURNO, PROMPT, PROVEDOR, conectar_servicos, conversar, get_ferramentas


async def responder(cliente, mensagem, historico, modelo, *, usar_cache=True, ferramentas=None):
    inicio = perf_counter()
    ultima_mensagem = historico[-1] if historico else None
    evidencias = []
    estado, similaridade = "ignorado", None
    modelo_embedding = os.getenv("MODELO_EMBEDDING", "").strip()
    elegivel = identificar_topico(mensagem) if not historico else None
    dinamico = bool(not elegivel and ferramentas is None and elegivel_dinamico(mensagem))
    topico, pergunta_publica = elegivel if elegivel else ("geral", normalizar(mensagem)) if dinamico else (None, None)
    cache, vetor = None, None

    async with asyncio.timeout(LIMITE_TURNO):
        if usar_cache and modelo_embedding and topico:
            try:
                cache = configurar_cache(f"{PROVEDOR}:{cliente.base_url}", modelo, modelo_embedding, PROMPT)
                retorno = await cliente.embeddings.create(model=modelo_embedding, input=pergunta_publica, timeout=8)
                vetor = retorno.data[0].embedding
                texto, similaridade = cache.buscar(topico, vetor)
                estado = "hit" if texto else "miss"
            except (APIError, OSError, sqlite3.Error, ValueError, IndexError, TypeError):
                estado, texto, cache = "indisponivel", None, None
        else:
            texto = None

        if estado == "hit":
            historico.extend([{"role": "user", "content": mensagem}, {"role": "assistant", "content": texto}])
        elif elegivel:
            referencia = ORIENTACOES[elegivel[0]][0]
            texto = await conversar(cliente, {}, mensagem, historico, modelo, evidencias,
                                    f"\nPara esta pergunta geral, responda exatamente: {referencia}")
            # Só compartilha respostas verificadas contra o conhecimento público versionado.
            if cache and estado == "miss" and texto.strip() == referencia:
                try:
                    cache.salvar(topico, pergunta_publica, referencia, vetor)
                except (OSError, sqlite3.Error, ValueError):
                    estado = "indisponivel"
        else:
            async with AsyncExitStack() as pilha:
                if ferramentas is None:
                    servicos = await conectar_servicos(pilha, tolerar_falhas=True)
                    ferramentas = await get_ferramentas(servicos)
                    if not ferramentas:
                        raise ConnectionError("Não foi possível conectar ao catálogo.")
                texto = await conversar(cliente, ferramentas, mensagem, historico, modelo, evidencias)
            if dinamico:
                concluido_turno = bool(historico and historico[-1] is not ultima_mensagem
                                       and historico[-1]["role"] == "assistant")
                if evidencias or not concluido_turno:
                    estado, similaridade = "ignorado", None
                elif cache and estado == "miss":
                    try:
                        cache.salvar(topico, pergunta_publica, texto.strip(), vetor)
                    except (OSError, sqlite3.Error, ValueError):
                        estado = "indisponivel"

    duracao_ms = round((perf_counter() - inicio) * 1000)
    logging.getLogger("especialista").info("cache=%s similaridade=%s latencia_ms=%s ferramentas=%s llm_evitado=%s",
        estado, similaridade, duracao_ms, [item["ferramenta"] for item in evidencias], estado == "hit")
    return {"resposta": texto, "evidencias": evidencias, "cache": estado,
            "similaridade": similaridade, "latencia_ms": duracao_ms,
            "concluido": bool(historico and historico[-1] is not ultima_mensagem
                              and historico[-1]["role"] == "assistant")}
