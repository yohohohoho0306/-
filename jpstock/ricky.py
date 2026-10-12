"""Ricky さんの増配株 3 段階スクリーニングの判定ロジック（ネットワーク不要）.

第1段階: 現在の状態（PER・PBR・ROE・ROA・配当利回り・自己資本比率・時価総額）
第2段階: 過去10期の実績（EPS・BPS・1株配当）
第3段階: 定性チェックのうち機械的に判定できるもの（配当方針の累進・DOE、PBR1倍前後）

EDINET には会社予想が載らないため、PER と配当利回りは実績ベースで計算する。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .history import History
from .xbrl import FiscalPeriod

FINANCIAL_INDUSTRIES = frozenset({"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"})


@dataclass(frozen=True)
class Criteria:
    per_max: float = 12.0
    pbr_max: float = 1.3
    roe_min: float = 7.0  # %
    roa_min: float = 3.0  # %
    yield_min: float = 3.0  # %
    equity_ratio_min: float = 35.0  # %
    market_cap_min: float = 10_000_000_000  # 100 億円
    periods: int = 10
    eps_growth_min: float = 2.0
    max_dividend_cuts: int = 1
    pbr_near_one: tuple[float, float] = (0.8, 1.2)


def is_financial(industry: Optional[str]) -> bool:
    return industry in FINANCIAL_INDUSTRIES


def _verdict(failures: list[str], missing: list[str]) -> Optional[bool]:
    """不合格が 1 つでもあれば False、未確認があれば None、それ以外は True."""
    if failures:
        return False
    if missing:
        return None
    return True


@dataclass
class Stage1:
    price: Optional[float]
    per: Optional[float] = None
    pbr: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    dividend_yield: Optional[float] = None
    equity_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    financial: bool = False
    failures: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def passed(self) -> Optional[bool]:
        return _verdict(self.failures, self.missing)


def evaluate_stage1(
    latest: FiscalPeriod,
    price: Optional[float],
    financial: bool = False,
    criteria: Criteria = Criteria(),
) -> Stage1:
    """直近期の実績と株価から第1段階を判定する（金融は ROA・自己資本比率を除外）."""
    s = Stage1(price=price, financial=financial, roe=latest.roe, roa=latest.roa,
               equity_ratio=latest.equity_ratio)
    if price is None or price <= 0:
        s.missing.append("株価")
    else:
        if latest.eps is not None and latest.eps > 0:
            s.per = price / latest.eps
        if latest.bps is not None and latest.bps > 0:
            s.pbr = price / latest.bps
        if latest.dps is not None:
            s.dividend_yield = latest.dps / price * 100.0
        if latest.shares:
            s.market_cap = price * latest.shares

    def check(label: str, value: Optional[float], ok: bool) -> None:
        if value is None:
            s.missing.append(label)
        elif not ok:
            s.failures.append(label)

    c = criteria
    loss = latest.eps is not None and latest.eps <= 0
    if loss:
        s.failures.append("PER（直近期赤字）")
    if price is not None and price > 0:
        if not loss:
            check("PER", s.per, s.per is not None and s.per <= c.per_max)
        check("PBR", s.pbr, s.pbr is not None and s.pbr <= c.pbr_max)
        check("配当利回り", s.dividend_yield, s.dividend_yield is not None and s.dividend_yield >= c.yield_min)
        check("時価総額", s.market_cap, s.market_cap is not None and s.market_cap >= c.market_cap_min)
    check("ROE", s.roe, s.roe is not None and s.roe >= c.roe_min)
    if not financial:
        check("ROA", s.roa, s.roa is not None and s.roa >= c.roa_min)
        check("自己資本比率", s.equity_ratio, s.equity_ratio is not None and s.equity_ratio >= c.equity_ratio_min)
    return s


@dataclass
class Stage2:
    n_periods: int
    first_end: Optional[date] = None
    last_end: Optional[date] = None
    eps_first: Optional[float] = None
    eps_last: Optional[float] = None
    eps_ratio: Optional[float] = None
    bps_first: Optional[float] = None
    bps_last: Optional[float] = None
    bps_growth: Optional[float] = None
    bps_streak: int = 0  # 直近期から遡った BPS の連続増加回数
    loss_periods: list[date] = field(default_factory=list)
    bps_decreases: list[date] = field(default_factory=list)
    dividend_cuts: list[date] = field(default_factory=list)
    dividend_suspended: list[date] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def passed(self) -> Optional[bool]:
        return _verdict(self.failures, self.missing)

    @property
    def bps_all_increase(self) -> bool:
        return self.n_periods > 1 and self.bps_streak == self.n_periods - 1


def evaluate_stage2(history: History, criteria: Criteria = Criteria()) -> Stage2:
    """直近 10 期の EPS・BPS・1株配当を判定する."""
    c = criteria
    periods = history.periods[-c.periods:]
    s = Stage2(n_periods=len(periods))
    if not periods:
        s.missing.append("決算データなし")
        return s
    s.first_end, s.last_end = periods[0].end, periods[-1].end
    if len(periods) < c.periods:
        s.missing.append(f"{c.periods}期分のデータなし（{len(periods)}期）")

    # EPS: 赤字なし、直近期 ÷ 9期前 ≧ 2
    eps = [p.eps for p in periods]
    s.loss_periods = [p.end for p in periods if p.eps is not None and p.eps <= 0]
    if s.loss_periods:
        s.failures.append("EPS赤字あり")
    if any(v is None for v in eps):
        s.missing.append("EPS欠損")
    s.eps_first, s.eps_last = eps[0], eps[-1]
    if s.eps_first and s.eps_last is not None and s.eps_first > 0:
        s.eps_ratio = s.eps_last / s.eps_first
        if len(periods) >= c.periods and s.eps_ratio < c.eps_growth_min:
            s.failures.append(f"EPS {c.eps_growth_min:g}倍未達")

    # BPS: 1 回でも前期を下回ったら不合格
    bps = [p.bps for p in periods]
    if any(v is None for v in bps):
        s.missing.append("BPS欠損")
    for prev, cur in zip(periods, periods[1:]):
        if prev.bps is not None and cur.bps is not None and cur.bps < prev.bps:
            s.bps_decreases.append(cur.end)
    if s.bps_decreases:
        s.failures.append("BPS減少あり")
    for i in range(len(bps) - 1, 0, -1):
        if bps[i] is None or bps[i - 1] is None or not bps[i] > bps[i - 1]:
            break
        s.bps_streak += 1
    s.bps_first, s.bps_last = bps[0], bps[-1]
    if s.bps_first and s.bps_last is not None and s.bps_first > 0:
        s.bps_growth = s.bps_last / s.bps_first

    # 1株配当: 減配は 1 回まで、無配転落なし（端数の丸め差 0.5% は減配とみなさない）
    if any(p.dps is None for p in periods):
        s.missing.append("1株配当欠損")
    for prev, cur in zip(periods, periods[1:]):
        if prev.dps is None or cur.dps is None:
            continue
        if prev.dps > 0 and cur.dps == 0:
            s.dividend_suspended.append(cur.end)
        elif cur.dps < prev.dps * (1 - 0.005):
            s.dividend_cuts.append(cur.end)
    if s.dividend_suspended:
        s.failures.append("無配転落あり")
    if len(s.dividend_cuts) + len(s.dividend_suspended) > c.max_dividend_cuts:
        s.failures.append(f"減配{len(s.dividend_cuts) + len(s.dividend_suspended)}回")
    return s


_DOE_RE = re.compile(
    r"(DOE|株主資本配当率|純資産配当率|自己資本配当率)[^%]{0,40}?(\d+(?:\.\d+)?)\s*%"
)


@dataclass
class Stage3:
    progressive: bool = False  # 配当方針に「累進」の記載
    doe: bool = False  # 配当方針に DOE の記載
    doe_values: list[float] = field(default_factory=list)
    pbr_near_one: Optional[bool] = None
    mark: str = ""  # ★: BPS連続増加+DOE+PBR1倍前後 / ☆: そのうち2つ


def evaluate_stage3(
    dividend_policy: Optional[str],
    pbr: Optional[float],
    bps_all_increase: bool,
    criteria: Criteria = Criteria(),
) -> Stage3:
    """有価証券報告書の「配当政策」の文面と PBR から機械判定できる部分を出す."""
    s = Stage3()
    text = unicodedata.normalize("NFKC", dividend_policy or "")
    s.progressive = "累進" in text
    s.doe = bool(re.search(r"DOE|株主資本配当率|純資産配当率|自己資本配当率", text))
    for m in _DOE_RE.finditer(text):
        value = float(m.group(2))
        if value not in s.doe_values:
            s.doe_values.append(value)
    if pbr is not None:
        lo, hi = criteria.pbr_near_one
        s.pbr_near_one = lo <= pbr <= hi
    hits = sum([bps_all_increase, s.doe, bool(s.pbr_near_one)])
    s.mark = "★" if hits == 3 else ("☆" if hits == 2 else "")
    return s
