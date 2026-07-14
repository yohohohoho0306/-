"""データモデル定義."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class StockSummary:
    """1 銘柄分のまとめ情報.

    値が取得できなかった項目は None になる。
    """

    # 識別情報
    ticker: str  # 例: "7203.T"
    code: str  # 例: "7203"
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: str = "JPY"

    # 株価・値動き
    price: Optional[float] = None  # 現在値（直近終値）
    previous_close: Optional[float] = None
    open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[float] = None

    # 52週レンジ
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None

    # 投資指標
    market_cap: Optional[float] = None
    per: Optional[float] = None  # PER (trailing)
    pbr: Optional[float] = None  # PBR
    dividend_yield: Optional[float] = None  # 配当利回り（比率, 0.025 = 2.5%）
    eps: Optional[float] = None

    # 企業概要
    summary: Optional[str] = None

    # ヒストリカルデータ（チャート用）
    history: Optional[pd.DataFrame] = field(default=None, repr=False)

    # 取得エラー（取得失敗時のみ設定）
    error: Optional[str] = None

    @property
    def change(self) -> Optional[float]:
        """前日終値からの変化額."""
        if self.price is None or self.previous_close is None:
            return None
        return self.price - self.previous_close

    @property
    def change_percent(self) -> Optional[float]:
        """前日終値からの変化率（%）."""
        if self.change is None or not self.previous_close:
            return None
        return self.change / self.previous_close * 100.0

    @property
    def ok(self) -> bool:
        return self.error is None
