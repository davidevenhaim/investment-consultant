from core.config import Settings, get_settings


def test_settings_loads_defaults() -> None:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        secret_key="test-key",
    )
    assert s.environment == "test"
    assert s.log_level == "INFO"
    # Default host port: Chroma container maps 8001 (host) → 8000 (container).
    # Local scripts and tests connect via localhost:8001.
    # Inside Docker the env override sets CHROMA_HOST=chroma CHROMA_PORT=8000.
    assert s.chroma_host == "localhost"
    assert s.chroma_port == 8001


def test_settings_is_production_false_in_dev() -> None:
    s = Settings(_env_file=None, environment="development")  # type: ignore[call-arg]
    assert s.is_production is False


def test_settings_is_production_true() -> None:
    s = Settings(_env_file=None, environment="production")  # type: ignore[call-arg]
    assert s.is_production is True


def test_chroma_url_property() -> None:
    s = Settings(_env_file=None, chroma_host="myhost", chroma_port=9000)  # type: ignore[call-arg]
    assert s.chroma_url == "http://myhost:9000"


def test_chroma_docker_url() -> None:
    # Values injected by docker-compose environment: block for api/worker/beat.
    # Chroma container internal port is 8000; host mapping is 8001:8000.
    s = Settings(_env_file=None, chroma_host="chroma", chroma_port=8000)  # type: ignore[call-arg]
    assert s.chroma_url == "http://chroma:8000"


def test_chroma_host_url() -> None:
    # Values for running scripts/tests directly on the host (outside Docker).
    s = Settings(_env_file=None, chroma_host="localhost", chroma_port=8001)  # type: ignore[call-arg]
    assert s.chroma_url == "http://localhost:8001"


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
