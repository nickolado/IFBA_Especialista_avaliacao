"""Consulta local e somente leitura dos relatórios produzidos pelo julgador."""
import json
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify

from julgador import ler_julgamento

rotas = Blueprint("relatorios_julgador", __name__)
LIMITE_ARQUIVO = 2_000_000


def pasta():
    return Path(current_app.config["PASTA_RELATORIOS"]).resolve()


def ler(nome):
    raiz = pasta()
    arquivo = raiz / nome
    if Path(nome).name != nome or not nome.endswith(".json") or arquivo.resolve().parent != raiz:
        raise FileNotFoundError
    with arquivo.open("rb") as entrada:
        conteudo = entrada.read(LIMITE_ARQUIVO + 1)
    if len(conteudo) > LIMITE_ARQUIVO:
        raise ValueError("Relatório muito grande")
    dados = json.loads(conteudo)
    if (not isinstance(dados, dict) or dados.get("versao") != 2
            or not isinstance(dados.get("resultados"), list)
            or not isinstance(dados.get("data_utc"), str)
            or not isinstance(dados.get("modelo_juiz"), str)
            or not isinstance(dados.get("modelo_assistente"), str)):
        raise ValueError("Não é um relatório do julgador")
    data = datetime.fromisoformat(dados["data_utc"].replace("Z", "+00:00"))
    if data.tzinfo is None:
        raise ValueError("Data sem fuso horário")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           or type(item.get("aprovado")) is not bool for item in dados["resultados"]):
        raise ValueError("Casos inválidos")
    return dados


def apresentar_caso(item):
    try:
        julgamento = ler_julgamento(json.dumps(item.get("julgamento")))
    except (ValueError, TypeError):
        julgamento = None
    # Uma falha registrada nunca vira nota zero nem aprovação inferida pela interface.
    if item.get("falha"):
        julgamento = None
    estado = "sem_notas" if julgamento is None else "aprovado" if item["aprovado"] else "reprovado"
    return {"id": item["id"], "estado": estado, "aprovado": item["aprovado"],
            "julgamento": julgamento, "falha": item.get("falha"),
            "referencia": item.get("referencia", ""), "fonte": item.get("fonte", ""),
            "erros_objetivos": item.get("erros_objetivos", []), "turnos": item.get("turnos", [])}


def resumir(nome, dados, casos):
    return {"arquivo": nome, "data_utc": dados["data_utc"],
            "modelo_assistente": dados["modelo_assistente"], "modelo_juiz": dados["modelo_juiz"],
            "provedor": dados.get("provedor"),
            "provedor_juiz": dados.get("provedor_juiz", dados.get("provedor")), "cache": dados.get("cache"),
            "total": len(casos), **{estado: sum(c["estado"] == estado for c in casos)
                                   for estado in ("aprovado", "reprovado", "sem_notas")}}


@rotas.get("/julgador/relatorios")
def listar():
    relatorios = []
    try:
        for arquivo in pasta().glob("*.json"):
            try:
                dados = ler(arquivo.name)
                casos = [apresentar_caso(item) for item in dados["resultados"]]
                relatorios.append(resumir(arquivo.name, dados, casos))
            except (ValueError, TypeError, OSError):
                continue
    except OSError:
        return jsonify(erro="Não foi possível acessar os relatórios."), 503
    relatorios.sort(key=lambda r: (datetime.fromisoformat(r["data_utc"].replace("Z", "+00:00")), r["arquivo"]), reverse=True)
    return jsonify(relatorios=relatorios)


@rotas.get("/julgador/relatorios/<nome>")
def consultar_relatorio(nome):
    try:
        dados = ler(nome)
        casos = [apresentar_caso(item) for item in dados["resultados"]]
        return jsonify(**resumir(nome, dados, casos), resultados=casos)
    except FileNotFoundError:
        return jsonify(erro="Relatório não encontrado."), 404
    except (ValueError, TypeError):
        return jsonify(erro="O arquivo não contém um relatório válido do julgador."), 422
    except OSError:
        return jsonify(erro="Não foi possível ler o relatório agora."), 503
