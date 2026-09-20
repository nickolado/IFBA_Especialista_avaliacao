import json
import urllib.request as requisicao
from urllib.error import HTTPError, URLError


def acessar(url):
    try:
        with requisicao.urlopen(url, timeout=5) as resposta:
            return json.load(resposta)
    except HTTPError as erro:
        return {"erro": f"O serviço respondeu HTTP {erro.code}. Não há dados confirmados."}
    except (URLError, TimeoutError, OSError, ValueError):
        return {"erro": "Serviço indisponível. Tente novamente; não considere isso uma lista vazia."}
