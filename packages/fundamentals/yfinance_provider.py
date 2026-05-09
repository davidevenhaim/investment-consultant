"""yfinance implementation of FundamentalsProvider."""

import datetime as dt
from typing import Any

import yfinance as yf
from core.errors import FundamentalsDataError
from core.logging import get_logger

from fundamentals.interfaces import FundamentalsProvider
from fundamentals.schemas import CompanyFundamentalsSnapshot

logger = get_logger(__name__)

_FIELD_MAP: dict[str, str] = {
    "marketCap": "market_cap",
    "trailingPE": "trailing_pe",
    "forwardPE": "forward_pe",
    "priceToBook": "price_to_book",
    "priceToSalesTrailing12Months": "price_to_sales",
    "enterpriseToRevenue": "enterprise_to_revenue",
    "enterpriseToEbitda": "enterprise_to_ebitda",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "earnings_growth",
    "profitMargins": "profit_margins",
    "grossMargins": "gross_margins",
    "operatingMargins": "operating_margins",
    "returnOnEquity": "return_on_equity",
    "debtToEquity": "debt_to_equity",
    "currentRatio": "current_ratio",
    "freeCashflow": "free_cashflow",
    "totalCash": "total_cash",
    "totalDebt": "total_debt",
}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


class YFinanceFundamentalsProvider(FundamentalsProvider):
    @property
    def provider_name(self) -> str:
        return "yfinance"

    def fetch_company_fundamentals(self, symbol: str) -> CompanyFundamentalsSnapshot:
        sym = symbol.upper()
        try:
            info: dict[str, Any] = yf.Ticker(sym).info or {}
        except Exception as exc:
            raise FundamentalsDataError(
                f"yfinance .info failed for {sym}: {exc}",
                {"symbol": sym, "provider": "yfinance"},
            ) from exc

        if not info or info.get("quoteType") is None:
            logger.warning("yfinance_fundamentals_empty", symbol=sym)
            return CompanyFundamentalsSnapshot(
                symbol=sym,
                as_of_date=dt.date.today(),
                provider="yfinance",
                raw_json=info,
            )

        kwargs: dict[str, Any] = {
            "symbol": sym,
            "as_of_date": dt.date.today(),
            "provider": "yfinance",
            "raw_json": {k: v for k, v in info.items() if isinstance(v, (int, float, str, bool))},
        }
        for yf_key, field in _FIELD_MAP.items():
            kwargs[field] = _safe_float(info.get(yf_key))

        # yfinance debtToEquity is always percentage-form.
        # 79.548 → 0.795x ratio. 7.25 → 0.0725x ratio. 0.8 → 0.008x ratio.
        # Divide unconditionally — raw value preserved in raw_json for audit.
        dte = kwargs.get("debt_to_equity")
        if dte is not None:
            kwargs["debt_to_equity"] = dte / 100.0

        snapshot = CompanyFundamentalsSnapshot(**kwargs)
        logger.info(
            "yfinance_fundamentals_ok",
            symbol=sym,
            completeness=snapshot.completeness_score,
        )
        return snapshot
