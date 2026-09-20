import os
from urllib.parse import quote
from mcp.server.fastmcp import FastMCP
from acesso import acessar

mcp = FastMCP("pedidos", host="0.0.0.0", port=int(os.getenv("PORTA", "8000")), stateless_http=True)
URL_PEDIDOS = os.getenv("URL_PEDIDOS", "http://pedidos:5000")


@mcp.tool()
def get_pedidos():
    """Lista os pedidos de locação, clientes, imóveis, datas e situações."""
    return acessar(f"{URL_PEDIDOS}/pedidos")


@mcp.tool()
def get_pedidos_por_situacao(situacao: str):
    """Filtra pedidos: pendente, aprovado, recusado, cancelado ou concluido."""
    return acessar(f"{URL_PEDIDOS}/pedidos/situacao/{quote(situacao, safe='')}")


@mcp.tool()
def get_pedido_por_id(id_pedido: int):
    """Consulta o andamento de um pedido pelo identificador."""
    return acessar(f"{URL_PEDIDOS}/pedidos/{id_pedido}")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
