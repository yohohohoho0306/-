"""ネットワーク不要のユニットテスト（モックの Ticker を使用）."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jpstock import fetcher, formatter
from jpstock.models import StockSummary


# ---- モック --------------------------------------------------------------

class FakeTicker:
    """yfinance.Ticker 互換のモック."""

    def __init__(self, info, hist):
        self._info = info
        self._hist = hist

    @property
    def info(self):
        return self._info

    def history(self, period="6mo"):
        return self._hist


def toyota_like():
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    hist = pd.DataFrame(
        {
            "Open": [2500, 2520, 2510],
            "High": [2530, 2540, 2560],
            "Low": [2490, 2500, 2505],
            "Close": [2520, 2510, 2550],
            "Volume": [1_000_000, 1_200_000, 900_000],
        },
        index=idx,
    )
    info = {
        "shortName": "TOYOTA MOTOR",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "currency": "JPY",
        "fiftyTwoWeekHigh": 3000,
        "fiftyTwoWeekLow": 2200,
        "marketCap": 40_000_000_000_000,
        "trailingPE": 10.5,
        "priceToBook": 1.2,
        "dividendYield": 0.025,
        "trailingEps": 240.0,
        "longBusinessSummary": "自動車の製造・販売を行う。",
    }
    return FakeTicker(info, hist)


# ---- normalize_ticker ----------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7203", "7203.T"),
        ("7203.T", "7203.T"),
        ("7203.JP", "7203.T"),
        (" 6758.t ", "6758.T"),
        ("^N225", "^N225"),
        ("AAPL", "AAPL"),
        ("135A", "135A.T"),  # 4桁+英字の新形式コード
    ],
)
def test_normalize_ticker(raw, expected):
    assert fetcher.normalize_ticker(raw) == expected


def test_normalize_ticker_empty():
    with pytest.raises(ValueError):
        fetcher.normalize_ticker("  ")


# ---- build_summary -------------------------------------------------------

def test_build_summary_basic():
    s = fetcher.build_summary_from_ticker(toyota_like(), "7203.T")
    assert s.ok
    assert s.code == "7203"
    assert s.name == "TOYOTA MOTOR"
    assert s.price == 2550
    assert s.previous_close == 2510
    assert s.change == pytest.approx(40)
    assert s.change_percent == pytest.approx(40 / 2510 * 100)
    assert s.per == 10.5
    assert s.dividend_yield == pytest.approx(0.025)
    assert s.market_cap == 40_000_000_000_000


def test_dividend_yield_percent_normalized():
    """dividendYield が % 表記(2.5)で来ても率(0.025)に正規化される."""
    t = toyota_like()
    t._info["dividendYield"] = 2.5
    s = fetcher.build_summary_from_ticker(t, "7203.T")
    assert s.dividend_yield == pytest.approx(0.025)


def test_nan_handled():
    t = toyota_like()
    t._info["trailingPE"] = float("nan")
    s = fetcher.build_summary_from_ticker(t, "7203.T")
    assert s.per is None


def test_empty_history_marks_error():
    t = FakeTicker({}, pd.DataFrame())
    s = fetcher.build_summary_from_ticker(t, "0000.T")
    assert not s.ok
    assert s.error is not None


def test_info_exception_recorded():
    class Boom:
        @property
        def info(self):
            raise RuntimeError("boom")

        def history(self, period="6mo"):
            return pd.DataFrame()

    s = fetcher.build_summary_from_ticker(Boom(), "7203.T")
    assert not s.ok
    assert "info" in s.error


# ---- フォーマッタ --------------------------------------------------------

def test_formatters_smoke():
    s = fetcher.build_summary_from_ticker(toyota_like(), "7203.T")

    plain = formatter.render_plain_table([s])
    assert "7203" in plain
    assert "TOYOTA MOTOR" in plain

    csv_out = formatter.render_csv([s])
    assert "コード" in csv_out
    assert "7203" in csv_out

    md = formatter.render_markdown([s])
    assert "# 日本株サマリーレポート" in md
    assert "PER" in md


def test_fmt_helpers():
    assert formatter.fmt_price(2550, "JPY") == "2,550"
    assert formatter.fmt_price(None) == "-"
    assert formatter.fmt_pct(0.025) == "2.50%"
    assert formatter.fmt_signed_pct(1.59) == "+1.59%"
    assert formatter.fmt_market_cap(40_000_000_000_000) == "40.00 兆円"
    assert formatter.fmt_market_cap(50_000_000_000) == "500 億円"


def test_error_row_rendered():
    bad = StockSummary(ticker="0000.T", code="0000", error="not found")
    plain = formatter.render_plain_table([bad])
    assert "取得失敗" in plain
    csv_out = formatter.render_csv([bad])
    assert "取得失敗" in csv_out
