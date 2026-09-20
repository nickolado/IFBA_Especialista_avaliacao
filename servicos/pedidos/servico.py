import os
from flask import Flask, jsonify, make_response, request
from banco import configurar, get_conexao_com_bd, texto_valido

servico = Flask(__name__)
configurar(servico)
DESCRICAO = "Serviço de pedidos de locação residencial"
VERSAO = "1.0"
SITUACOES = ["pendente", "aprovado", "recusado", "cancelado", "concluido"]


@servico.get("/")
def get_info():
    return make_response(jsonify(descricao=DESCRICAO, versao=VERSAO), 200)


@servico.get("/pedidos")
def get_pedidos():
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.pedidos ORDER BY pedido_id")
        pedidos = cursor.fetchall()
    return make_response(jsonify(pedidos), 200)


@servico.get("/pedidos/situacao/<string:situacao>")
def get_pedidos_por_situacao(situacao):
    if situacao not in SITUACOES:
        return jsonify(erro="Situação inválida."), 400
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.pedidos WHERE situacao = %s ORDER BY pedido_id", (situacao,))
        pedidos = cursor.fetchall()
    return make_response(jsonify(pedidos), 200)


@servico.get("/pedidos/<int:id_pedido>")
def get_pedido_por_id(id_pedido):
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.pedidos WHERE pedido_id = %s", (id_pedido,))
        pedido = cursor.fetchone()
    if not pedido:
        return jsonify(erro="Pedido não encontrado."), 404
    return make_response(jsonify(pedido), 200)


@servico.post("/pedidos")
def cadastrar_pedido():
    formulario = request.get_json()
    if not isinstance(formulario, dict):
        return jsonify(erro="Envie um objeto JSON."), 400
    if not texto_valido(formulario.get("cliente"), 120):
        return jsonify(erro="Informe o cliente com até 120 caracteres."), 400
    id_imovel = formulario.get("imovel_id")
    if type(id_imovel) is not int or id_imovel <= 0:
        return jsonify(erro="Informe um identificador de imóvel inteiro positivo."), 400
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT imovel_id FROM locacao.imoveis WHERE imovel_id = %s", (id_imovel,))
        if not cursor.fetchone():
            return jsonify(erro="Imóvel não encontrado."), 404
        # Um pedido pendente registra interesse; não garante reserva.
        cursor.execute("""
            INSERT INTO locacao.pedidos (cliente, imovel_id) VALUES (%s, %s) RETURNING *
        """, (formulario["cliente"].strip(), id_imovel))
        pedido = cursor.fetchone()
    return make_response(jsonify(pedido), 201)


@servico.patch("/pedidos/<int:id_pedido>/situacao")
def alterar_situacao_pedido(id_pedido):
    formulario = request.get_json()
    if not isinstance(formulario, dict) or formulario.get("situacao") not in SITUACOES:
        return jsonify(erro="Informe uma situação válida."), 400
    situacao = formulario["situacao"]
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        # O bloqueio evita duas alterações simultâneas no mesmo pedido.
        cursor.execute("SELECT * FROM locacao.pedidos WHERE pedido_id = %s FOR UPDATE", (id_pedido,))
        pedido = cursor.fetchone()
        if not pedido:
            return jsonify(erro="Pedido não encontrado."), 404
        if situacao == pedido["situacao"]:
            return jsonify(pedido), 200
        permitidas = {"pendente": ["aprovado", "recusado", "cancelado"],
                      "aprovado": ["concluido", "cancelado"]}
        if situacao not in permitidas.get(pedido["situacao"], []):
            return jsonify(erro="Mudança de situação não permitida."), 409
        # O índice único do banco impede duas reservas ou locações do mesmo imóvel.
        cursor.execute("UPDATE locacao.pedidos SET situacao = %s WHERE pedido_id = %s RETURNING *",
                       (situacao, id_pedido))
        pedido = cursor.fetchone()
    return make_response(jsonify(pedido), 200)


if __name__ == "__main__":
    servico.run(host="0.0.0.0", port=int(os.getenv("PORTA", "5000")))
