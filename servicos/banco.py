import os
import psycopg as dados
from psycopg.rows import dict_row as dicionario
from flask import jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException


def get_conexao_com_bd():
    return dados.connect(
        host=os.getenv("SERVIDOR_BANCO", "dados"),
        port=os.getenv("PORTA_BANCO", "5432"),
        user=os.getenv("USUARIO_BANCO", "admin"),
        password=os.getenv("SENHA_BANCO", "admin"),
        dbname=os.getenv("NOME_BANCO", "locacao"),
        row_factory=dicionario,
        connect_timeout=3,
        options="-c statement_timeout=4000 -c lock_timeout=3000",
    )


def configurar(servico):
    servico.json.ensure_ascii = False
    servico.config["MAX_CONTENT_LENGTH"] = 16384
    CORS(servico, origins=["http://localhost:8088", "http://127.0.0.1:8088"])

    @servico.errorhandler(HTTPException)
    def erro_http(erro):
        return jsonify(erro=erro.description), erro.code

    @servico.errorhandler(dados.IntegrityError)
    def erro_integridade(erro):
        return jsonify(erro="Operação incompatível com os dados. Verifique duplicidade e referências."), 409

    @servico.errorhandler(dados.OperationalError)
    def erro_banco(erro):
        return jsonify(erro="Banco de dados indisponível. Tente novamente."), 503


def texto_valido(valor, limite):
    return isinstance(valor, str) and 0 < len(valor.strip()) <= limite
