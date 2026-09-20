"""Consulta as nove ferramentas reais, sem chamar nem cobrar a IA."""
import asyncio
import json
from contextlib import AsyncExitStack
from chat_ai import conectar_servicos


async def testar():
    argumentos = {"get_imoveis_por_situacao": {"situacao": "disponivel"},
                  "get_imovel_por_id": {"id_imovel": 1},
                  "get_pedidos_por_situacao": {"situacao": "pendente"},
                  "get_pedido_por_id": {"id_pedido": 1},
                  "get_avaliacoes_por_imovel": {"id_imovel": 3}}
    nomes = set()
    async with AsyncExitStack() as pilha:
        servicos = await conectar_servicos(pilha)
        for conexao in servicos:
            ferramentas = await conexao.list_tools()
            assert len(ferramentas.tools) >= 2
            for ferramenta in ferramentas.tools:
                assert ferramenta.name not in nomes, "Os nomes das ferramentas precisam ser únicos."
                nomes.add(ferramenta.name)
                resultado = await conexao.call_tool(ferramenta.name, argumentos.get(ferramenta.name, {}))
                assert not resultado.isError, resultado
                for parte in resultado.content:
                    if parte.type == "text":
                        dados = json.loads(parte.text)
                        assert not (isinstance(dados, dict) and "erro" in dados), dados
                print("OK:", ferramenta.name)
    assert len(nomes) == 9
    print("OK: nove ferramentas MCP consultaram os três serviços REST.")


if __name__ == "__main__":
    asyncio.run(testar())
