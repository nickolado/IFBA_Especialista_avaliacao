import os
from mcp.server.fastmcp import FastMCP
from acesso import acessar

mcp = FastMCP("avaliacoes", host="0.0.0.0", port=int(os.getenv("PORTA", "8000")), stateless_http=True)
URL_AVALIACOES = os.getenv("URL_AVALIACOES", "http://avaliacoes:5000")


@mcp.tool()
def get_avaliacoes():
    """Lista avaliações, notas e comentários de clientes com locações concluídas."""
    return acessar(f"{URL_AVALIACOES}/avaliacoes")


@mcp.tool()
def get_avaliacoes_por_imovel(id_imovel: int):
    """Consulta as avaliações de um imóvel pelo identificador."""
    return acessar(f"{URL_AVALIACOES}/avaliacoes/imovel/{id_imovel}")


@mcp.tool()
def get_resumo_avaliacoes():
    """Consulta a quantidade de avaliações e a nota média de cada imóvel avaliado."""
    return acessar(f"{URL_AVALIACOES}/avaliacoes/resumo")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
