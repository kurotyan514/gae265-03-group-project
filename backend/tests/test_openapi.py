"""OpenAPI 文件：前端由它產生 client，operationId 決定產生出來的函式名。"""

from httpx import AsyncClient


async def operation_ids(client: AsyncClient) -> dict[str, str]:
    """`"<method> <path>"` → operationId。"""
    spec = (await client.get("/openapi.json")).json()
    return {
        f"{method} {path}": operation["operationId"]
        for path, operations in spec["paths"].items()
        for method, operation in operations.items()
    }


async def test_operation_id_is_route_function_name(client: AsyncClient) -> None:
    ids = await operation_ids(client)

    assert ids["get /api/v1/health"] == "health"


async def test_operation_ids_are_unique(client: AsyncClient) -> None:
    ids = list((await operation_ids(client)).values())

    assert len(ids) == len(set(ids))
