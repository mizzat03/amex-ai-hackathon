from pathlib import Path


def test_redis_healthcheck_requires_an_exact_pong_before_dependents_start() -> None:
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert 'redis-cli --raw ping 2>/dev/null | grep -qx PONG' in compose
    assert 'test: ["CMD", "redis-cli", "ping"]' not in compose


def test_redis_healthcheck_allows_persisted_aof_replay_before_failing() -> None:
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    redis_service = compose.split("\n  redis:\n", maxsplit=1)[1].split(
        "\nvolumes:\n", maxsplit=1
    )[0]

    assert "start_period: 5m" in redis_service


def test_postgres_healthcheck_allows_crash_recovery_before_failing() -> None:
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    postgres_service = compose.split("\n  postgres:\n", maxsplit=1)[1].split(
        "\n  redis:\n", maxsplit=1
    )[0]

    assert "start_period: 5m" in postgres_service
