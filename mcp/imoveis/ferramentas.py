import os
from urllib.parse import quote
from mcp.server.fastmcp import FastMCP
from acesso import acessar

mcp = FastMCP("imoveis", host="0.0.0.0", port=int(os.getenv("PORTA", "8000")), stateless_http=True)
URL_IMOVEIS = os.getenv("URL_IMOVEIS", "http://imoveis:5000")


@mcp.tool()
def get_imoveis():
    """Lista todos os imóveis, com bairro, tipo, quartos, valor mensal e situação."""
    return acessar(f"{URL_IMOVEIS}/imoveis")


@mcp.tool()
def get_imoveis_por_situacao(situacao: str):
    """Lista imóveis por situação: disponivel, reservado ou alugado (sem acentos)."""
    return acessar(f"{URL_IMOVEIS}/imoveis/situacao/{quote(situacao, safe='')}")


@mcp.tool()
def get_imovel_por_id(id_imovel: int):
    """Consulta os dados de um imóvel pelo identificador."""
    return acessar(f"{URL_IMOVEIS}/imoveis/{id_imovel}")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
