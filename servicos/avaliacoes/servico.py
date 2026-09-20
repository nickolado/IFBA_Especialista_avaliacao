import os
from flask import Flask, jsonify, make_response, request
from banco import configurar, get_conexao_com_bd, texto_valido

servico = Flask(__name__)
configurar(servico)
DESCRICAO = "Serviço de avaliações de locações residenciais"
VERSAO = "1.0"


@servico.get("/")
def get_info():
    return make_response(jsonify(descricao=DESCRICAO, versao=VERSAO), 200)


@servico.get("/avaliacoes")
def get_avaliacoes():
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.vw_avaliacoes ORDER BY avaliacao_id")
        avaliacoes = cursor.fetchall()
    return make_response(jsonify(avaliacoes), 200)


@servico.get("/avaliacoes/imovel/<int:id_imovel>")
def get_avaliacoes_por_imovel(id_imovel):
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.vw_avaliacoes WHERE imovel_id = %s ORDER BY avaliacao_id", (id_imovel,))
        avaliacoes = cursor.fetchall()
    return make_response(jsonify(avaliacoes), 200)


@servico.get("/avaliacoes/resumo")
def get_resumo_avaliacoes():
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("""
            SELECT imovel_id, COUNT(*) AS quantidade, ROUND(AVG(nota), 2) AS media_nota
            FROM locacao.vw_avaliacoes GROUP BY imovel_id ORDER BY imovel_id
        """)
        resumo = cursor.fetchall()
    return make_response(jsonify(resumo), 200)


@servico.post("/avaliacoes")
def cadastrar_avaliacao():
    formulario = request.get_json()
    if not isinstance(formulario, dict):
        return jsonify(erro="Envie um objeto JSON."), 400
    id_pedido = formulario.get("pedido_id")
    nota = formulario.get("nota")
    if type(id_pedido) is not int or id_pedido <= 0:
        return jsonify(erro="Informe um identificador de pedido inteiro positivo."), 400
    if type(nota) is not int or not 1 <= nota <= 5:
        return jsonify(erro="A nota deve ser um inteiro de 1 a 5."), 400
    if not texto_valido(formulario.get("comentario"), 500):
        return jsonify(erro="Informe um comentário com até 500 caracteres."), 400
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT situacao FROM locacao.pedidos WHERE pedido_id = %s", (id_pedido,))
        pedido = cursor.fetchone()
        if not pedido:
            return jsonify(erro="Pedido não encontrado."), 404
        if pedido["situacao"] != "concluido":
            return jsonify(erro="Somente uma locação concluída permite avaliação."), 409
        # Cliente e imóvel vêm do pedido: não podem ser trocados no formulário.
        cursor.execute("""
            INSERT INTO locacao.avaliacoes (pedido_id, nota, comentario)
            VALUES (%s, %s, %s) RETURNING avaliacao_id
        """, (id_pedido, nota, formulario["comentario"].strip()))
        id_avaliacao = cursor.fetchone()["avaliacao_id"]
        cursor.execute("SELECT * FROM locacao.vw_avaliacoes WHERE avaliacao_id = %s", (id_avaliacao,))
        avaliacao = cursor.fetchone()
    return make_response(jsonify(avaliacao), 201)


if __name__ == "__main__":
    servico.run(host="0.0.0.0", port=int(os.getenv("PORTA", "5000")))
