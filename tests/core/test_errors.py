from core.errors import (
    DatabaseError,
    InvestmentConsultantError,
    LLMError,
    LLMParseError,
    NotFoundError,
    ValidationError,
)


def test_base_error_attributes() -> None:
    err = InvestmentConsultantError("something broke", detail={"key": "value"})
    assert err.message == "something broke"
    assert err.detail == {"key": "value"}
    assert err.status_code == 500
    assert err.error_code == "INTERNAL_ERROR"


def test_not_found_error() -> None:
    err = NotFoundError("recommendation not found")
    assert err.status_code == 404
    assert err.error_code == "NOT_FOUND"


def test_validation_error() -> None:
    err = ValidationError("invalid score")
    assert err.status_code == 422


def test_database_error_inherits_external_service() -> None:
    err = DatabaseError("connection failed")
    assert err.status_code == 503
    assert isinstance(err, InvestmentConsultantError)


def test_llm_parse_error_inherits_llm_error() -> None:
    err = LLMParseError("bad json from claude")
    assert isinstance(err, LLMError)
    assert err.error_code == "LLM_PARSE_ERROR"


def test_error_default_detail_is_empty_dict() -> None:
    err = NotFoundError("missing")
    assert err.detail == {}
