"""Cache compartilhado apenas para perguntas públicas e independentes da sessão."""
import json
import math
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path

TERMOS_DINAMICOS = re.compile(
    r"^(?:e|mas|entao|ou)\b|#\s*\d+|\b(?:\d+|\w+\s+quartos?|quartos?|r\$|reais|mil|dispon[ií]ve(?:l|is)|"
    r"alugad[oa]s?|reservad[oa]s?|pendentes?|aprovad[oa]s?|conclu[ií]d[oa]s?|cancelad[oa]s?|recusad[oa]s?|"
    r"avaliac\w*|nota\w*|media|meu|minha|meus|minhas|cpf|telefone|email|centro|sao\s+jose|"
    r"primavera|universitario|jardim\s+america|vila\s+serrana|recomen\w*|procur\w*|busc\w*|"
    r"compar\w*|opco\w*|opca\w*|quais\s+imoveis)\b"
)


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto.lower().strip().rstrip("?.!"))
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def elegivel_dinamico(mensagem):
    consulta = normalizar(mensagem)
    return bool(consulta and len(consulta) <= 200 and not TERMOS_DINAMICOS.search(consulta))


# Perguntas públicas de referência para orientação inicial.
ORIENTACOES = {
    "pendencia": (
        "Um pedido pendente registra interesse e não reserva o imóvel.",
        ("O que significa um pedido pendente?", "Qual o significado de pedido pendente?",
         "O que quer dizer pedido pendente?", "O que é um pedido pendente?"),
    ),
    "reserva": (
        "No sistema, a aprovação do pedido reserva o imóvel; a conclusão efetiva a locação.",
        ("Quando o imóvel fica reservado?", "Em que momento o imóvel é reservado?",
         "Em qual etapa o imóvel é reservado?", "Quando acontece a reserva do imóvel?"),
    ),
    "avaliacao": (
        "A avaliação só pode ser registrada após a conclusão do pedido, uma vez por locação.",
        ("Quando posso avaliar um imóvel?", "Em que momento posso registrar uma avaliação?",
         "Em qual etapa posso avaliar o imóvel?", "Quando é possível registrar uma avaliação?"),
    ),
}


def identificar_topico(mensagem):
    consulta = normalizar(mensagem)
    for topico, (_, perguntas) in ORIENTACOES.items():
        for pergunta in perguntas:
            if consulta == normalizar(pergunta):
                return topico, pergunta
    return None


def unitario(vetor):
    norma = math.hypot(*vetor)
    if not norma or not math.isfinite(norma):
        raise ValueError("Embedding sem norma válida.")
    return [valor / norma for valor in vetor]


class CacheSemantico:
    def __init__(self, arquivo, assinatura, limiar=0.85, validade=86400):
        if not 0 < limiar <= 1 or validade <= 0:
            raise ValueError("Limiar ou validade inválidos.")
        self.arquivo = Path(arquivo)
        self.assinatura = assinatura
        self.limiar = limiar
        self.validade = validade

    @contextmanager
    def conexao(self):
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.arquivo)) as banco, banco:
            banco.execute("""CREATE TABLE IF NOT EXISTS respostas (
                assinatura TEXT, topico TEXT, pergunta TEXT, resposta TEXT, vetor TEXT,
                criacao REAL, expira REAL, PRIMARY KEY (assinatura, topico, pergunta)
            )""")
            yield banco

    def buscar(self, topico, vetor):
        consulta = unitario(vetor)
        with self.conexao() as banco:
            linhas = banco.execute("SELECT resposta, vetor FROM respostas "
                                  "WHERE assinatura=? AND topico=? AND expira>?",
                                  (self.assinatura, topico, time.time())).fetchall()
        melhor = (None, None)
        for resposta, armazenado in linhas:
            candidato = json.loads(armazenado)
            if len(consulta) != len(candidato):
                continue
            similaridade = min(1.0, math.fsum(a * b for a, b in zip(consulta, candidato)))
            if melhor[1] is None or similaridade > melhor[1]:
                melhor = resposta, similaridade
        resposta, similaridade = melhor
        return (resposta if similaridade is not None and similaridade >= self.limiar else None, similaridade)

    def salvar(self, topico, pergunta, resposta, vetor):
        agora = time.time()
        with self.conexao() as banco:
            banco.execute("DELETE FROM respostas WHERE expira<=?", (agora,))
            banco.execute("INSERT OR REPLACE INTO respostas VALUES (?, ?, ?, ?, ?, ?, ?)", (
                self.assinatura, topico, pergunta, resposta, json.dumps(unitario(vetor)), agora, agora + self.validade,
            ))

    def limpar(self):
        with self.conexao() as banco:
            banco.execute("DELETE FROM respostas")


def configurar_cache(provedor, modelo, modelo_embedding, prompt):
    assinatura = sha256(json.dumps([provedor, modelo, modelo_embedding, prompt, ORIENTACOES],
                                   ensure_ascii=False).encode()).hexdigest()
    return CacheSemantico(os.getenv("CACHE_ARQUIVO", ".cache-local/respostas.sqlite3"), assinatura,
                         float(os.getenv("CACHE_LIMIAR", "0.85")), int(os.getenv("CACHE_TTL", "86400")))


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Manutenção do cache semântico da Locação v2")
    cli.add_argument("acao", choices=["limpar"])
    cli.parse_args()
    CacheSemantico(os.getenv("CACHE_ARQUIVO", ".cache-local/respostas.sqlite3"), "").limpar()
    print("Cache semântico limpo.")
