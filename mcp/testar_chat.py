"""Testa o chat sem internet, chaves reais ou serviços iniciados."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch
import httpx2
from openai import AsyncOpenAI
import chat_ai


async def testar():
    async def listar():
        return SimpleNamespace(tools=[SimpleNamespace(
            name="get_imoveis", description="Lista imóveis",
            inputSchema={"type": "object", "properties": {}},
        )])

    configuracoes = {**chat_ai.PROVEDORES, "outro": ("http://host.docker.internal:11434/v1", "CHAVE_API_IA", "qwen3:8b")}
    for provedor, (url, nome_chave, modelo) in configuracoes.items():
        with patch.object(chat_ai, "PROVEDOR", provedor), patch.object(chat_ai, "MODELO", modelo if provedor == "outro" else ""), patch.dict(
            "os.environ", {nome_chave: "teste", "URL_IA": url}, clear=True
        ):
            assert chat_ai.configurar_ia() == (url, "teste", modelo)
        for caso in ["sucesso", "falha_mcp", "json_invalido", "desconhecida", "limite"]:
            chamadas = []
            consultas = []

            async def consultar(nome, arguments):
                consultas.append(nome)
                assert nome == "get_imoveis" and arguments == {}
                if caso == "falha_mcp":
                    raise ConnectionError("MCP desligado")
                return SimpleNamespace(isError=False, content=[SimpleNamespace(text='{"imovel_id": 1}')])

            async def simular(requisicao):
                corpo = json.loads(requisicao.content)
                chamadas.append(corpo)
                assert str(requisicao.url) == url.rstrip("/") + "/chat/completions"
                assert corpo["model"] == modelo
                assert corpo["tools"][0]["function"]["name"] == "get_imoveis"
                if len(chamadas) == 1 or caso == "limite":
                    mensagem = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": f"consulta-{len(chamadas)}", "type": "function",
                        "function": {"name": "ausente" if caso == "desconhecida" else "get_imoveis",
                                     "arguments": "[" if caso == "json_invalido" else "{}"},
                        "extra_content": {"google": {"thought_signature": "assinatura-teste"}},
                    }]}
                else:
                    retorno = json.loads(corpo["messages"][-1]["content"])
                    assert bool(retorno["erro"]) == (caso != "sucesso")
                    assert corpo["messages"][-1]["tool_call_id"] == "consulta-1"
                    assert corpo["messages"][-2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "assinatura-teste"
                    mensagem = {"role": "assistant", "content": "Consulta finalizada."}
                return httpx2.Response(200, json={"id": "teste", "object": "chat.completion",
                    "created": 0, "model": modelo, "choices": [{"index": 0,
                    "message": mensagem, "finish_reason": "tool_calls" if "tool_calls" in mensagem else "stop"}]})

            conexao = SimpleNamespace(list_tools=listar, call_tool=consultar)
            ferramentas = await chat_ai.get_ferramentas([conexao])
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(simular)) as transporte:
                async with AsyncOpenAI(api_key="teste", base_url=url, http_client=transporte) as cliente:
                    historico = []
                    resposta = await chat_ai.conversar(cliente, ferramentas, "Liste imóveis", historico, modelo)
            if caso == "limite":
                assert len(chamadas) == 10 and historico == [] and "limite" in resposta
            else:
                assert resposta == "Consulta finalizada." and len(historico) == 4
                assert len(chamadas) == 2
                assert len(consultas) == (0 if caso in ["json_invalido", "desconhecida"] else 1)
        print(f"OK: {provedor}, ferramentas, histórico, falhas e limite de etapas.")
    with patch.object(chat_ai, "PROVEDOR", "outro"), patch.object(chat_ai, "MODELO", "meu-modelo"), patch.dict(
        "os.environ", {"URL_IA": "https://exemplo.test/v1", "CHAVE_API_IA": "teste"}, clear=True
    ):
        assert chat_ai.configurar_ia() == ("https://exemplo.test/v1", "teste", "meu-modelo")
    with patch.dict("os.environ", {}, clear=True), patch.object(chat_ai, "PROVEDOR", "openai"):
        try:
            chat_ai.configurar_ia()
            raise AssertionError("Aceitou chave ausente")
        except ValueError:
            pass
    print("OK: configuração adicional e chave obrigatória. Nenhuma chamada externa realizada.")


def testar_modelos_independentes():
    with patch.object(chat_ai, "PROVEDOR", "google"), patch.object(chat_ai, "MODELO", "gemini-teste"), patch.dict(
        "os.environ", {"GOOGLE_API_KEY": "chave-chat"}, clear=True
    ):
        assert chat_ai.configurar_juiz() == chat_ai.configurar_ia()
        with patch.dict("os.environ", {"MODELO_JUIZ": "gemini-juiz"}):
            assert chat_ai.configurar_juiz()[1:] == ("chave-chat", "gemini-juiz")
        with patch.dict("os.environ", {"PROVEDOR_JUIZ": "outro", "MODELO_JUIZ": "qwen3:8b",
                                      "URL_JUIZ": "http://host.docker.internal:11434/v1", "CHAVE_API_JUIZ": "ollama"}):
            assert chat_ai.configurar_juiz() == ("http://host.docker.internal:11434/v1", "ollama", "qwen3:8b")
            assert chat_ai.configurar_ia()[1:] == ("chave-chat", "gemini-teste")
        with patch.dict("os.environ", {"PROVEDOR_JUIZ": "openai", "MODELO_JUIZ": "juiz-teste", "CHAVE_API_JUIZ": "chave-juiz"}):
            assert chat_ai.configurar_juiz() == ("https://api.openai.com/v1", "chave-juiz", "juiz-teste")
        for variaveis in ({"URL_JUIZ": "https://exemplo.test/v1"},
                          {"PROVEDOR_JUIZ": "outro", "MODELO_JUIZ": "qwen3", "URL_JUIZ": "http://localhost:11434/v1"},
                          {"PROVEDOR_JUIZ": "google", "URL_JUIZ": "https://exemplo.test/v1"}):
            with patch.dict("os.environ", variaveis):
                try:
                    chat_ai.configurar_juiz()
                    raise AssertionError("Configuração ambígua ou incompleta aceita")
                except ValueError:
                    pass
    for host in ("localhost", "127.0.0.1", "[::1]", "host.docker.internal"):
        url = f"http://{host}:11434/v1"
        assert chat_ai.configurar_ia(provedor="outro", modelo="qwen3", url=url, chave="ollama") == (url, "ollama", "qwen3")
    for url in ("http://localhost.exemplo.test/v1", "http://publico.test/v1", "https://chave:senha@exemplo.test/v1", "file:///tmp/modelo"):
        try:
            chat_ai.configurar_ia(provedor="outro", modelo="teste", url=url, chave="teste")
            raise AssertionError("URL inválida aceita")
        except ValueError:
            pass
    print("OK: modelos locais, juiz independente, herança de configuração e validação de URLs.")


if __name__ == "__main__":
    testar_modelos_independentes()
    asyncio.run(testar())
