import sys
from pathlib import Path

import pytest

# Ensure packages/ is importable without Docker PYTHONPATH
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "packages"))
sys.path.insert(0, str(_root))


@pytest.fixture(autouse=True)
def override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/investment_test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8001")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
