
from core.config import Settings, get_settings


def test_settings_loads_defaults() -> None:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        secret_key="test-key",
    )
    assert s.environment == "test"
    assert s.log_level == "INFO"
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


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
