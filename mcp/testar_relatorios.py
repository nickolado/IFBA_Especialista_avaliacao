"""Testes de leitura de relatórios em pasta temporária, sem chamadas à IA."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from chat_web import app
from julgador import CRITERIOS
from relatorios_julgador import LIMITE_ARQUIVO


def executar():
    parecer = {"notas": dict.fromkeys(CRITERIOS, 5), "justificativa": "Conforme evidências.", "sem_suporte": []}
    documento = {"versao": 2, "data_utc": "2026-11-14T17:00:00+00:00", "modelo_juiz": "teste",
                 "modelo_assistente": "teste", "cache": False, "segredo_nao_exportar": "teste",
                 "resultados": [
                     {"id": "ok", "aprovado": True, "julgamento": parecer},
                     {"id": "ids", "aprovado": False, "julgamento": parecer, "erros_objetivos": ["ID divergente"]},
                     {"id": "invalido", "aprovado": False, "falha": "ValueError"},
                 ]}
    with TemporaryDirectory() as diretorio, patch.dict(app.config, {"PASTA_RELATORIOS": diretorio}), app.test_client() as cliente:
        raiz = Path(diretorio)
        assert cliente.get("/julgador/relatorios").json == {"relatorios": []}
        (raiz / "antigo.json").write_text(json.dumps(documento), encoding="utf-8")
        (raiz / "novo.json").write_text(json.dumps({**documento, "data_utc": "2026-11-17T10:00:00Z"}), encoding="utf-8")
        (raiz / "cache.json").write_text('{"aprovado":true,"turnos":[]}', encoding="utf-8")
        (raiz / "quebrado.json").write_text('{', encoding="utf-8")
        (raiz / "grande.json").write_bytes(b' ' * (LIMITE_ARQUIVO + 1))
        resposta = cliente.get("/julgador/relatorios", headers={"Origin": "http://localhost:8088"})
        assert resposta.status_code == 200
        assert resposta.headers["Access-Control-Allow-Origin"] == "http://localhost:8088"
        assert resposta.headers["Cache-Control"] == "no-store"
        assert [r["arquivo"] for r in resposta.json["relatorios"]] == ["novo.json", "antigo.json"]
        dados = cliente.get("/julgador/relatorios/novo.json").json
        assert (dados["total"], dados["aprovado"], dados["reprovado"], dados["sem_notas"]) == (3, 1, 1, 1)
        assert dados["resultados"][1]["julgamento"]["notas"]["clareza"] == 5
        assert dados["resultados"][1]["estado"] == "reprovado"
        assert dados["resultados"][2]["julgamento"] is None
        assert "segredo_nao_exportar" not in dados
        assert cliente.get("/julgador/relatorios/falta.json").status_code == 404
        for nome in ("quebrado.json", "cache.json", "grande.json"):
            assert cliente.get(f"/julgador/relatorios/{nome}").status_code == 422
        assert cliente.get("/julgador/relatorios/%2e%2e%2f.env").status_code == 404
        assert cliente.get("/julgador/relatorios", headers={"Origin": "https://fora.example"}).status_code == 403
        assert cliente.post("/julgador/relatorios").status_code == 405
        # Links para fora da pasta não podem expor outros arquivos do ambiente.
        with TemporaryDirectory() as outra:
            alvo = Path(outra) / "fora.json"
            alvo.write_text(json.dumps(documento), encoding="utf-8")
            (raiz / "atalho.json").symlink_to(alvo)
            assert cliente.get("/julgador/relatorios/atalho.json").status_code == 404
            assert len(cliente.get("/julgador/relatorios").json["relatorios"]) == 2
    print("OK: relatórios, notas ausentes, reprovação com nota alta, ordenação, erros, CORS e limite de arquivos.")


if __name__ == "__main__":
    executar()
