"""Teste com banco temporário: python testar.py. Não altera os dados da apresentação."""
import importlib.util
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from psycopg import sql
from banco import get_conexao_com_bd

PASTA = Path(__file__).resolve().parent


def carregar(nome):
    especificacao = importlib.util.spec_from_file_location("teste_" + nome, PASTA / nome / "servico.py")
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    modulo.servico.config["TESTING"] = True
    return modulo.servico


def testar():
    imoveis = carregar("imoveis").test_client()
    servico_pedidos = carregar("pedidos")
    pedidos = servico_pedidos.test_client()
    avaliacoes = carregar("avaliacoes").test_client()
    assert len(imoveis.get("/imoveis").json) == 12
    assert imoveis.get("/imoveis/1").json["situacao"] == "disponivel"
    assert imoveis.get("/imoveis/2").json["situacao"] == "reservado"
    assert imoveis.get("/imoveis/3").json["situacao"] == "alugado"
    assert len(pedidos.get("/pedidos/situacao/pendente").json) == 4
    assert len(avaliacoes.get("/avaliacoes").json) == 3
    assert avaliacoes.get("/avaliacoes/resumo").json[0]["media_nota"] == "5.00"
    for cliente, rota in [(imoveis, "/imoveis"), (pedidos, "/pedidos"), (avaliacoes, "/avaliacoes")]:
        for corpo in [[], None, {"nota": True}]:
            assert cliente.post(rota, json=corpo).status_code in [400, 415]
    assert imoveis.get("/imoveis/situacao/invalida").status_code == 400
    assert imoveis.get("/imoveis/99999").status_code == 404
    assert pedidos.post("/pedidos", json={"cliente": "Teste", "imovel_id": 99999}).status_code == 404
    assert pedidos.patch("/pedidos/1/situacao", json={"situacao": "concluido"}).status_code == 409
    assert avaliacoes.post("/avaliacoes", json={"pedido_id": 1, "nota": 5, "comentario": "Teste"}).status_code == 409

    # Duas aprovações ao mesmo tempo: exatamente uma deve vencer.
    def aprovar(numero):
        with servico_pedidos.test_client() as cliente:
            return numero, cliente.patch(f"/pedidos/{numero}/situacao", json={"situacao": "aprovado"}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(aprovar, [1, 2]))
    assert sorted(codigo for _, codigo in resultados) == [200, 409], resultados
    vencedor = next(numero for numero, codigo in resultados if codigo == 200)
    outro = 2 if vencedor == 1 else 1
    assert imoveis.get("/imoveis/1").json["situacao"] == "reservado"
    assert pedidos.patch(f"/pedidos/{vencedor}/situacao", json={"situacao": "cancelado"}).status_code == 200
    assert imoveis.get("/imoveis/1").json["situacao"] == "disponivel"
    assert pedidos.patch(f"/pedidos/{outro}/situacao", json={"situacao": "aprovado"}).status_code == 200
    assert pedidos.patch(f"/pedidos/{outro}/situacao", json={"situacao": "concluido"}).status_code == 200
    assert imoveis.get("/imoveis/1").json["situacao"] == "alugado"
    assert pedidos.patch(f"/pedidos/{outro}/situacao", json={"situacao": "cancelado"}).status_code == 409
    novo = pedidos.post("/pedidos", json={"cliente": "Outra pessoa", "imovel_id": 1})
    assert novo.status_code == 201
    assert pedidos.patch(f"/pedidos/{novo.json['pedido_id']}/situacao", json={"situacao": "aprovado"}).status_code == 409
    avaliacao = {"pedido_id": outro, "nota": 4, "comentario": "Bom imóvel."}
    assert avaliacoes.post("/avaliacoes", json=avaliacao).status_code == 201
    assert avaliacoes.post("/avaliacoes", json=avaliacao).status_code == 409
    for nota in [0, 6, True, 2.5, "5"]:
        assert avaliacoes.post("/avaliacoes", json={**avaliacao, "nota": nota}).status_code == 400
    assert avaliacoes.get("/avaliacoes/imovel/1").json[0]["pedido_id"] == outro
    cadastro = {"descricao": "Casa teste", "bairro": "Centro", "tipo": "casa", "quartos": 2, "valor_mensal": 900}
    assert imoveis.post("/imoveis", json=cadastro).status_code == 201
    for valor in [True, -1, "900", float("nan"), float("inf"), 10**1000]:
        assert imoveis.post("/imoveis", json={**cadastro, "valor_mensal": valor}).status_code == 400
    assert pedidos.get("/pedidos/1").status_code == 200
    assert pedidos.get("/pedidos/situacao/concluido").status_code == 200
    print("OK: consultas, cadastros, validação, concorrência, cancelamento, conclusão e avaliação única.")


if __name__ == "__main__":
    banco_original = os.getenv("NOME_BANCO", "locacao")
    banco_teste = "locacao_teste_" + uuid4().hex
    os.environ["NOME_BANCO"] = "postgres"
    with get_conexao_com_bd() as administracao:
        administracao.autocommit = True
        administracao.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(banco_teste)))
        try:
            os.environ["NOME_BANCO"] = banco_teste
            with get_conexao_com_bd() as conexao:
                conexao.execute((PASTA / "locacao.sql").read_text(encoding="utf-8"))
            testar()
        finally:
            os.environ["NOME_BANCO"] = banco_original
            administracao.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(banco_teste)))
