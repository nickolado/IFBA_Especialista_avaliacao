"""Verifica os fluxos da v2 com IA e MCP simulados, sem acesso externo."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import patch

import chat_web
import julgador
from cache_semantico import CacheSemantico, ORIENTACOES
from especialista import responder


class Mensagem(NS):
    def model_dump(self, **_):
        return {"role": "assistant", **vars(self)}


def retorno(texto=None, chamada=None):
    return NS(choices=[NS(finish_reason="stop", message=Mensagem(content=texto, tool_calls=chamada))])


async def testar_cache_e_catalogo():
    chamadas = []
    embeddings = []
    estado_catalogo = "disponivel"
    resposta_faq = ORIENTACOES["pendencia"][0]

    async def embedding(input, **_):
        embeddings.append(input)
        return NS(data=[NS(embedding=[0.97, 0.12] if "quer dizer" in input else [1.0, 0.0])])

    async def gerar(messages, **_):
        chamadas.append(messages)
        if "responda exatamente" in messages[0]["content"]:
            return retorno(resposta_faq)
        if messages[-1]["role"] == "tool":
            dados = json.loads(messages[-1]["content"])["dados"][0]
            return retorno(dados[0]["situacao"])
        return retorno(chamada=[NS(id="consulta", function=NS(name="get_imoveis", arguments="{}"))])

    async def consultar(_nome, arguments):
        return NS(isError=False, content=[NS(text=json.dumps([{"imovel_id": 1, "situacao": estado_catalogo}]))])

    cliente = NS(base_url="https://teste.invalid/v1", embeddings=NS(create=embedding), chat=NS(completions=NS(create=gerar)))
    ferramentas = {"get_imoveis": {"conexao": NS(call_tool=consultar), "declaracao": {}}}
    with TemporaryDirectory() as pasta, patch.dict("os.environ", {
        "CACHE_ARQUIVO": str(Path(pasta) / "teste.sqlite3"), "MODELO_EMBEDDING": "teste",
        "CACHE_LIMIAR": "0.85", "CACHE_TTL": "86400",
    }):
        pergunta, parafrase = "O que significa um pedido pendente?", "O que quer dizer pedido pendente?"
        conversa = []
        primeira = await responder(cliente, pergunta, conversa, "teste")
        segunda = await responder(cliente, parafrase, [], "teste")
        assert primeira["cache"] == "miss" and segunda["cache"] == "hit" and len(chamadas) == 1
        assert segunda["resposta"] == resposta_faq and len(set(embeddings)) == 2
        assert segunda["similaridade"] > 0.85
        for consulta, historico in [(parafrase, conversa), ("Meu pedido pendente reserva?", [])]:
            assert (await responder(cliente, consulta, historico, "teste", ferramentas=ferramentas))["cache"] == "ignorado"
        assert len(embeddings) == 2
        for esperado in ("disponivel", "reservado"):
            estado_catalogo = esperado
            resultado = await responder(cliente, "O imóvel #1 está disponível?", [], "teste", ferramentas=ferramentas)
            assert resultado["resposta"] == esperado and resultado["cache"] == "ignorado" and resultado["evidencias"]

        resposta_faq = "Resposta incompleta."
        consulta = "Quando o imóvel fica reservado?"
        for _ in range(2):
            assert (await responder(cliente, consulta, [], "teste"))["cache"] == "miss"

        async def gerar_geral(messages, **_):
            return retorno("Trabalhamos apenas com locação residencial.")

        cliente_geral = NS(base_url="https://teste.invalid/v1", embeddings=NS(create=embedding),
                           chat=NS(completions=NS(create=gerar_geral)))
        with patch("especialista.conectar_servicos", return_value=[]), patch(
            "especialista.get_ferramentas", return_value={"get_imoveis": {"conexao": NS(call_tool=consultar), "declaracao": {}}}
        ):
            d1 = await responder(cliente_geral, "tem apartamentos para venda?", [], "teste")
            d2 = await responder(cliente_geral, "tem apartamentos para venda?", [], "teste")
            assert d1["cache"] == "miss" and d2["cache"] == "hit" and d2["resposta"] == d1["resposta"]

        arquivo = Path(pasta) / "expira.sqlite3"
        cache = CacheSemantico(arquivo, "versao-a", validade=1)
        with patch("cache_semantico.time.time", return_value=100):
            cache.salvar("reserva", "pergunta", "resposta", [1, 0])
            assert CacheSemantico(arquivo, "versao-a").buscar("reserva", [1, 0])[0] == "resposta"
            assert cache.buscar("reserva", [0, 1])[0] is None
            assert cache.buscar("pendencia", [1, 0])[0] is None
            assert CacheSemantico(arquivo, "versao-b").buscar("reserva", [1, 0])[0] is None
        with patch("cache_semantico.time.time", return_value=101):
            assert cache.buscar("reserva", [1, 0])[0] is None


def testar_web():
    async def consultar(mensagem, historico, _configuracao):
        if mensagem == "falhar":
            raise ConnectionError
        historico.append({"role": "user", "content": mensagem})
        return {"resposta": str(len(historico)), "concluido": True}

    origem = {"Origin": "http://localhost:8088"}
    with chat_web.app.test_client() as cliente, patch.object(chat_web, "consultar", consultar), patch.object(
        chat_web, "configurar_ia", return_value=("teste", "teste", "teste")
    ), patch.object(chat_web, "SESSOES", {}):
        assert cliente.get("/saude").json["versao"] == 2
        assert cliente.post("/chat", json={"mensagem": "ok"}, headers={"Origin": "https://externo.test"}).status_code == 403
        primeira = cliente.post("/chat", json={"mensagem": "ok"}, headers=origem)
        assert primeira.headers["Access-Control-Allow-Origin"] == origem["Origin"]
        token = primeira.json["sessao"]
        assert cliente.post("/chat", json={"mensagem": "ok", "sessao": token}).json["resposta"] == "2"
        assert cliente.post("/chat", json={"mensagem": "ok"}).json["resposta"] == "1"
        assert cliente.post("/chat", json={"mensagem": "x" * 1501}).status_code == 400
        assert cliente.post("/chat", json={"mensagem": "falhar", "sessao": token}).status_code == 503
        assert cliente.post("/chat", json={"mensagem": "ok", "sessao": token}).json["resposta"] == "3"

    async def consultar_com_evidencias(mensagem, historico, _configuracao):
        historico.append({"role": "user", "content": mensagem})
        em_cache = mensagem == "pergunta em cache"
        return {"resposta": f"Recomendação para: {mensagem}", "evidencias": [],
                "cache": "hit" if em_cache else "miss",
                "similaridade": 0.99 if em_cache else None, "latencia_ms": 120, "concluido": True}

    julgamentos_web = 0

    async def julgar_web_simulado(_juiz, _modelo, item):
        nonlocal julgamentos_web
        julgamentos_web += 1
        item["julgamento"] = {"notas": dict.fromkeys(julgador.CRITERIOS, 5), "justificativa": "OK.", "sem_suporte": []}
        item["aprovado"] = True

    with TemporaryDirectory() as pasta, chat_web.app.test_client() as cliente, patch.dict(
        chat_web.app.config, {"PASTA_RELATORIOS": pasta}
    ), patch.object(chat_web, "consultar", consultar_com_evidencias), patch.object(
        chat_web, "configurar_ia", return_value=("teste", "teste", "teste")
    ), patch.object(chat_web, "configurar_juiz", return_value=("teste", "teste", "juiz-teste")), patch.object(
        chat_web, "julgar_caso", julgar_web_simulado
    ), patch.object(chat_web, "SESSOES", {}):
        r1 = cliente.post("/chat", json={"mensagem": "Procuro imóvel no Centro"}, headers=origem).json
        assert r1["avaliacao"]["estado"] == "aprovado" and r1["avaliacao"]["arquivo"] == "chat-web.json"
        assert r1["cache"] == "miss" and julgamentos_web == 1
        r2 = cliente.post("/chat", json={"mensagem": "Até R$ 1.500", "sessao": r1["sessao"]}, headers=origem).json
        assert r2["avaliacao"]["id"] == r1["avaliacao"]["id"] and julgamentos_web == 2
        r_hit = cliente.post("/chat", json={"mensagem": "pergunta em cache"}, headers=origem).json
        assert r_hit["cache"] == "hit" and "avaliacao" not in r_hit and julgamentos_web == 2
        relatorio = cliente.get("/julgador/relatorios/chat-web.json").json
        assert relatorio["total"] == 1 and len(relatorio["resultados"][0]["turnos"]) == 2
        assert relatorio["resultados"][0]["fonte"] == "chat_web"


async def testar_julgador():
    async def inferir(_cliente, _pergunta, _historico, _modelo, **opcoes):
        assert opcoes["usar_cache"] is False
        return {"resposta": "Imóvel #1", "concluido": True, "evidencias": [{"ferramenta": "get_imoveis", "erro": False,
            "dados": [[{"imovel_id": 1, "situacao": "disponivel", "valor_mensal": "1200.00"}]]}]}

    async def julgar(model, response_format, **_):
        assert model == "modelo-juiz"
        assert response_format == {"type": "json_object"}
        return retorno(json.dumps(parecer))

    cliente = NS(chat=NS(completions=NS(create=julgar)))
    caso = json.loads(julgador.CASOS.read_text(encoding="utf-8"))[0]
    parecer = {"notas": dict.fromkeys(julgador.CRITERIOS, 5), "justificativa": "Correto.", "sem_suporte": []}
    with patch.object(julgador, "responder", inferir):
        assert (await julgador.avaliar(cliente, "modelo-chat", "modelo-juiz", [caso]))["resultados"][0]["aprovado"]
        separado = await julgador.avaliar(NS(), "modelo-chat", "modelo-juiz", [caso],
                                         cliente_juiz=cliente, provedor_juiz="outro")
        assert separado["resultados"][0]["aprovado"] and separado["provedor_juiz"] == "outro"
        assert not (await julgador.avaliar(cliente, "modelo-chat", "modelo-juiz", [{**caso, "ids": [6]}]))["resultados"][0]["aprovado"]
        assert not (await julgador.avaliar(cliente, "modelo-chat", "modelo-juiz", [{**caso, "teto": 1199}]))["resultados"][0]["aprovado"]
        parecer["notas"]["clareza"] = True
        falha = (await julgador.avaliar(cliente, "modelo-chat", "modelo-juiz", [caso]))["resultados"][0]
        assert not falha["aprovado"] and falha["falha"] == "ValueError"

    for ferramenta in ("get_avaliacoes_por_imovel", "get_resumo_avaliacoes"):
        assert not julgador.conferir({"ferramenta": ["get_avaliac", "get_resumo_avaliacoes"]}, [
            {"concluido": True, "evidencias": [{"ferramenta": ferramenta, "erro": False}]}])
    assert julgador.ids_recomendados("Recomendo o Imóvel #1.\n(Nota: o imóvel #4 ultrapassa o limite.)") == {1}
    assert julgador.ler_julgamento("```json\n" + json.dumps(
        {"notas": dict.fromkeys(julgador.CRITERIOS, 5), "justificativa": "OK.", "sem_suporte": []}
    ) + "\n```")["notas"]["clareza"] == 5

    async def falhar(*_, **__):
        raise ConnectionError

    with patch.object(julgador, "responder", falhar), patch.dict("os.environ", {"MODELO_EMBEDDING": "teste"}):
        falha_cache = await julgador.medir_cache(cliente, "teste")
        assert not falha_cache["aprovado"] and falha_cache["turnos"][0]["falha"] == "ConnectionError"


if __name__ == "__main__":
    asyncio.run(testar_cache_e_catalogo())
    testar_web()
    asyncio.run(testar_julgador())
    print("OK: cache, catálogo atualizado, sessões web e julgamento simulado.")
