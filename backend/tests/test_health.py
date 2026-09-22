from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- 🔒 the suite must never point at production ---


def test_the_suite_runs_against_a_local_database() -> None:
    """The check that makes a whole class of incident impossible.

    Four times in one day the suite damaged the live database — scratch rows
    left in the real candidate pool, nine shipped library blocks deleted by an
    over-broad fixture, a profile overwritten with test values. Every one was
    caught after the fact, by a guard that noticed the damage.

    `conftest` now refuses to start against a remote host. This asserts the
    setting actually took effect, so the refusal cannot be silently bypassed by
    an environment that sets DATABASE_URL some other way.
    """
    from app.core.config import settings

    assert any(
        marker in settings.database_url
        for marker in ("localhost", "127.0.0.1", "@db:", "host.docker.internal")
    ), f"tests are pointed at a non-local database: {settings.database_url}"
