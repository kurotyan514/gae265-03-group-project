from app.core.config import Settings
from sqlalchemy.engine import make_url


def test_database_uri_keeps_special_characters_in_password() -> None:
    s = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        POSTGRES_PASSWORD="p@ss/w#rd:1",
        POSTGRES_SERVER="db",
        POSTGRES_PORT=6543,
    )
    url = make_url(s.SQLALCHEMY_DATABASE_URI)
    assert url.password == "p@ss/w#rd:1"
    assert url.host == "db"
    assert url.port == 6543
