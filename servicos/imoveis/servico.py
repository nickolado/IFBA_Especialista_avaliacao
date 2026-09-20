import math
import os
from flask import Flask, jsonify, make_response, request
from banco import configurar, get_conexao_com_bd, texto_valido

servico = Flask(__name__)
configurar(servico)
DESCRICAO = "Serviço de imóveis e disponibilidade da Locação Residencial"
VERSAO = "1.0"


@servico.get("/")
def get_info():
    return make_response(jsonify(descricao=DESCRICAO, versao=VERSAO), 200)


@servico.get("/imoveis")
def get_imoveis():
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.vw_imoveis ORDER BY imovel_id")
        imoveis = cursor.fetchall()
    return make_response(jsonify(imoveis), 200)


@servico.get("/imoveis/situacao/<string:situacao>")
def get_imoveis_por_situacao(situacao):
    if situacao not in ["disponivel", "reservado", "alugado"]:
        return jsonify(erro="Situação inválida."), 400
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.vw_imoveis WHERE situacao = %s ORDER BY imovel_id", (situacao,))
        imoveis = cursor.fetchall()
    return make_response(jsonify(imoveis), 200)


@servico.get("/imoveis/<int:id_imovel>")
def get_imovel_por_id(id_imovel):
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT * FROM locacao.vw_imoveis WHERE imovel_id = %s", (id_imovel,))
        imovel = cursor.fetchone()
    if not imovel:
        return jsonify(erro="Imóvel não encontrado."), 404
    return make_response(jsonify(imovel), 200)


@servico.post("/imoveis")
def cadastrar_imovel():
    formulario = request.get_json()
    if not isinstance(formulario, dict):
        return jsonify(erro="Envie um objeto JSON."), 400
    if not all(texto_valido(formulario.get(campo), limite) for campo, limite in
               [("descricao", 200), ("bairro", 80), ("tipo", 40)]):
        return jsonify(erro="Informe descrição (200), bairro (80) e tipo (40 caracteres)."), 400
    quartos = formulario.get("quartos")
    valor = formulario.get("valor_mensal")
    if type(quartos) is not int or not 0 <= quartos <= 50:
        return jsonify(erro="Quartos deve ser um inteiro de 0 a 50."), 400
    if type(valor) not in [int, float] or not 0.01 <= valor <= 99999999.99 or not math.isfinite(valor):
        return jsonify(erro="Valor mensal deve ser um número entre 0,01 e 99.999.999,99."), 400
    with get_conexao_com_bd() as conexao:
        cursor = conexao.cursor()
        cursor.execute("""
            INSERT INTO locacao.imoveis (descricao, bairro, tipo, quartos, valor_mensal)
            VALUES (%s, %s, %s, %s, %s) RETURNING imovel_id
        """, (formulario["descricao"].strip(), formulario["bairro"].strip(),
              formulario["tipo"].strip(), quartos, valor))
        id_imovel = cursor.fetchone()["imovel_id"]
        cursor.execute("SELECT * FROM locacao.vw_imoveis WHERE imovel_id = %s", (id_imovel,))
        imovel = cursor.fetchone()
    return make_response(jsonify(imovel), 201)


if __name__ == "__main__":
    servico.run(host="0.0.0.0", port=int(os.getenv("PORTA", "5000")))
