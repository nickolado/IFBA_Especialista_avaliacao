import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from time import monotonic

from flask import Flask, jsonify, request
from openai import AsyncOpenAI

from chat_ai import LIMITE_MENSAGEM, PROMPT, PROVEDOR, configurar_ia, configurar_juiz
from especialista import responder
from julgador import RUBRICA, julgar_caso
from relatorios_julgador import rotas as rotas_julgador

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=12_000, TRUSTED_HOSTS=["localhost", "127.0.0.1"])
app.config["PASTA_RELATORIOS"] = "resultados"
app.register_blueprint(rotas_julgador)
ORIGENS = {"http://localhost:8088", "http://127.0.0.1:8088"}
ARQUIVO_CHAT_WEB = "chat-web.json"
REFERENCIA_CHAT_WEB = (
    "Atender às regras do especialista em locação residencial (mcp/conhecimento.md): recomendar apenas imóveis "
    "disponíveis compatíveis com as restrições declaradas segundo as evidências MCP, solicitar informações "
    "faltantes quando necessário, não inventar dados ausentes e respeitar as regras de pedidos e avaliações."
)
SESSOES = {}
TRAVA = Lock()
TRAVA_RELATORIO = Lock()


@app.before_request
def verificar_origem():
    origem = request.headers.get("Origin")
    if origem and origem not in ORIGENS:
        return jsonify(erro="Origem não autorizada."), 403


@app.after_request
def adicionar_cors(resposta):
    origem = request.headers.get("Origin")
    if origem in ORIGENS:
        resposta.headers.update({"Access-Control-Allow-Origin": origem,
                                 "Access-Control-Allow-Headers": "Content-Type",
                                 "Access-Control-Allow-Methods": "GET, POST, OPTIONS"})
        resposta.vary.add("Origin")
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.errorhandler(413)
def corpo_grande(_erro):
    return jsonify(erro="Mensagem muito grande."), 413


@app.get("/saude")
def saude():
    return {"servico": "locacao-residencial", "versao": 2}


async def consultar(mensagem, historico, configuracao):
    url, chave, modelo = configuracao
    async with AsyncOpenAI(api_key=chave, base_url=url, timeout=25, max_retries=0) as cliente:
        return await responder(cliente, mensagem, historico, modelo)


def salvar_relatorio_web(item, modelo_assistente, modelo_juiz, provedor_juiz):
    pasta = Path(app.config["PASTA_RELATORIOS"]).resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / ARQUIVO_CHAT_WEB
    with TRAVA_RELATORIO:
        existentes = []
        if arquivo.exists():
            try:
                dados = json.loads(arquivo.read_text(encoding="utf-8"))
                if isinstance(dados, dict) and isinstance(dados.get("resultados"), list):
                    existentes = [c for c in dados["resultados"] if isinstance(c, dict) and isinstance(c.get("id"), str)]
            except (ValueError, OSError):
                existentes = []
        if not item.get("id"):
            resumo = " ".join(item["turnos"][0]["pergunta"].split())
            resumo = resumo[:36] + ("…" if len(resumo) > 36 else "")
            item["id"] = f"Conversa #{len(existentes) + 1} — {resumo}"
        resultados = [item] + [c for c in existentes if c["id"] != item["id"]]
        relatorio = {
            "versao": 2,
            "data_utc": datetime.now(timezone.utc).isoformat(),
            "provedor": PROVEDOR,
            "modelo_assistente": modelo_assistente,
            "modelo_juiz": modelo_juiz,
            "provedor_juiz": provedor_juiz,
            "cache": bool(os.getenv("MODELO_EMBEDDING", "").strip()),
            "formato_juiz": "json_object",
            "prompt_sha256": sha256(PROMPT.encode()).hexdigest(),
            "rubrica_sha256": sha256(RUBRICA.encode()).hexdigest(),
            "resultados": resultados,
        }
        arquivo.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return item["id"]


async def avaliar_conversa_web(sessao, mensagem, resultado, configuracao):
    _, _, modelo = configuracao
    turnos = sessao.setdefault("turnos", [])
    turnos.append({
        "pergunta": mensagem,
        "resposta": resultado["resposta"],
        "evidencias": resultado.get("evidencias", []),
        "cache": resultado.get("cache", "ignorado"),
        "similaridade": resultado.get("similaridade"),
        "latencia_ms": resultado.get("latencia_ms"),
        "concluido": bool(resultado.get("concluido")),
    })
    if len(turnos) > 6:
        del turnos[:-6]
    item = {
        "id": sessao.get("id_relatorio", ""),
        "referencia": REFERENCIA_CHAT_WEB,
        "fonte": "chat_web",
        "turnos": list(turnos),
        "erros_objetivos": [] if all(t["concluido"] for t in turnos) else ["Inferência sem resposta completa"],
    }
    provedor_juiz = os.getenv("PROVEDOR_JUIZ", "").strip().lower() or PROVEDOR
    modelo_juiz = modelo
    try:
        url_juiz, chave_juiz, modelo_juiz = configurar_juiz()
        async with AsyncOpenAI(api_key=chave_juiz, base_url=url_juiz, timeout=25, max_retries=0) as juiz:
            await julgar_caso(juiz, modelo_juiz, item)
    except Exception as erro:
        item.update(aprovado=False, falha=type(erro).__name__)
    try:
        sessao["id_relatorio"] = salvar_relatorio_web(item, modelo, modelo_juiz, provedor_juiz)
    except OSError as erro:
        app.logger.warning("Falha ao salvar avaliação do chat web: %s", type(erro).__name__)
        return None
    estado = "sem_notas" if item.get("falha") else "aprovado" if item["aprovado"] else "reprovado"
    return {"arquivo": ARQUIVO_CHAT_WEB, "id": sessao["id_relatorio"], "aprovado": item["aprovado"], "estado": estado}


@app.post("/chat")
def chat():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or not isinstance(dados.get("mensagem"), str):
        return jsonify(erro="Envie uma mensagem de texto."), 400
    mensagem = dados["mensagem"].strip()
    token = dados.get("sessao")
    if not mensagem or len(mensagem) > LIMITE_MENSAGEM:
        return jsonify(erro=f"Escreva uma mensagem de 1 a {LIMITE_MENSAGEM} caracteres."), 400
    if token is not None and (not isinstance(token, str) or len(token) != 32):
        return jsonify(erro="Sessão inválida. Inicie uma nova conversa."), 400
    try:
        configuracao = configurar_ia()
    except ValueError:
        return jsonify(erro="O assistente ainda não foi configurado. Confira o provedor e a chave no servidor."), 503

    # Sessões mantidas em memória para execução local.
    with TRAVA:
        agora = monotonic()
        for chave, sessao in list(SESSOES.items()):
            if not sessao["ocupada"] and agora - sessao["atividade"] > 1800:
                del SESSOES[chave]
        nova = token is None
        if nova:
            if len(SESSOES) >= 100:
                return jsonify(erro="Muitas conversas ativas. Tente novamente mais tarde."), 503
            token = token_urlsafe(24)
            SESSOES[token] = {"historico": [], "atividade": agora, "ocupada": False}
        sessao = SESSOES.get(token)
        if sessao is None:
            return jsonify(erro="A conversa expirou. Inicie uma nova conversa."), 410
        if sessao["ocupada"]:
            return jsonify(erro="Aguarde a resposta em andamento."), 409
        sessao["ocupada"] = True

    sucesso = False
    try:
        resultado = asyncio.run(consultar(mensagem, sessao["historico"], configuracao))
        if not resultado["concluido"]:
            return jsonify(erro=resultado["resposta"]), 503
        estado_cache = resultado.get("cache")
        avaliacao = (asyncio.run(avaliar_conversa_web(sessao, mensagem, resultado, configuracao))
                     if "evidencias" in resultado and estado_cache != "hit" else None)
        sucesso = True
        return jsonify(
            sessao=token,
            resposta=resultado["resposta"],
            **({"cache": estado_cache, "similaridade": resultado.get("similaridade")} if estado_cache else {}),
            **({"avaliacao": avaliacao} if avaliacao else {}),
        )
    except Exception as erro:
        app.logger.warning("Falha no chat: %s", type(erro).__name__)
        return jsonify(erro="Não foi possível consultar o assistente agora. Tente novamente."), 503
    finally:
        with TRAVA:
            sessao.update(ocupada=False, atividade=monotonic())
            if nova and not sucesso:
                del SESSOES[token]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=8090)
