from httpx import AsyncClient


async def test_health_checks_db_and_pgvector(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "db": "ok", "pgvector": "ok"}
