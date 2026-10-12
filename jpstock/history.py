"""複数の有価証券報告書をつないで 10 期分の系列を作る層（ネットワーク不要）.

1 通の有価証券報告書には 5 期分しか載っていないため、新しい報告書と
4〜5 年前の報告書を重ねて 10 期分にする。

株式分割・併合の扱い:
- EPS / BPS は、重複する期の値の比から古い報告書の値を新しい基準に合わせる。
- 1 株配当は報告書上で遡って修正されないため、期末発行済株式総数の
  「きりのよい倍率」での増減を分割・併合とみなし、それより前の期を割り戻す。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from statistics import median
from typing import Optional

from .xbrl import AnnualReport, FiscalPeriod

_BASE_RATIOS = [1.5, 2, 3, 4, 5, 10, 20, 50, 100]
SPLIT_RATIOS = sorted(set(_BASE_RATIOS + [1 / r for r in _BASE_RATIOS]))


@dataclass
class History:
    """古い順の決算期（1 株指標は最新の株式数基準にそろえた値）."""

    periods: list[FiscalPeriod]
    splits: list[tuple[date, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def nearest_split_ratio(ratio: float, tol: float = 0.03) -> Optional[float]:
    """株式数の比が分割・併合の倍率（2倍, 1/5 など）に近ければその倍率を返す."""
    for candidate in SPLIT_RATIOS:
        if abs(ratio / candidate - 1) <= tol:
            return candidate
    return None


def _same_period(a: date, b: date, tol_days: int = 20) -> bool:
    return abs((a - b).days) <= tol_days


def _basis_factor(newer: list[FiscalPeriod], older: AnnualReport, notes: list[str]) -> float:
    """古い報告書の EPS/BPS を新しい基準に合わせる係数を、重複する期から求める."""
    pairs = [
        (n, o) for o in older.periods for n in newer if _same_period(n.end, o.end)
    ]
    if not pairs:
        notes.append(f"報告書 {older.doc_id} と重複する期がなく、1株指標の基準合わせができない（要確認）")
        return 1.0
    ratios = [n.bps / o.bps for n, o in pairs if n.bps and o.bps]
    if not ratios:
        ratios = [n.eps / o.eps for n, o in pairs if n.eps and o.eps and (n.eps > 0) == (o.eps > 0)]
    if not ratios:
        return 1.0
    factor = median(ratios)
    if abs(factor - 1) <= 0.03:
        return 1.0
    split = nearest_split_ratio(factor, tol=0.05)
    if split is not None:
        notes.append(f"報告書 {older.doc_id} の EPS・BPS を係数 {split:g} で新しい基準に換算（分割・併合）")
        return split
    notes.append(f"報告書 {older.doc_id} と重複期の BPS/EPS が一致しない（比 {factor:.3f}、要確認）")
    return 1.0


def merge_reports(reports: list[AnnualReport]) -> History:
    """報告書（新しい順）をつないで History を作る."""
    notes: list[str] = []
    if not reports:
        return History(periods=[], notes=["有価証券報告書がない"])

    merged = [replace(p) for p in reports[0].periods]
    for older in reports[1:]:
        factor = _basis_factor(merged, older, notes)
        for p in older.periods:
            if any(_same_period(p.end, m.end) for m in merged):
                continue  # 新しい報告書の値を優先
            q = replace(p)
            if q.eps is not None:
                q.eps *= factor
            if q.bps is not None:
                q.bps *= factor
            merged.append(q)
    merged.sort(key=lambda p: p.end)

    splits: list[tuple[date, float]] = []
    for i in range(1, len(merged)):
        prev, cur = merged[i - 1], merged[i]
        if not prev.shares or not cur.shares:
            continue
        ratio = cur.shares / prev.shares
        if 0.72 < ratio < 1.4:
            continue
        split = nearest_split_ratio(ratio)
        if split is None:
            notes.append(f"{cur.end} 期に発行済株式数が {ratio:.2f} 倍に変化（分割以外の可能性、要確認）")
            continue
        splits.append((cur.end, split))
        notes.append(f"{cur.end} 期に株式分割・併合（{split:g} 倍）を検出。以前の期の1株配当を割り戻した")
        # 1 株配当は遡って修正されないので、分割前の期を割り戻す
        for j in range(i):
            if merged[j].dps is not None:
                merged[j].dps /= split
        # EPS/BPS も未修正（分割の前後で BPS が倍率どおりに飛ぶ）なら割り戻す
        if prev.bps and cur.bps:
            observed = prev.bps / cur.bps
            if split / 1.35 <= observed <= split * 1.35:
                notes.append(f"{cur.end} 期より前の EPS・BPS が分割未修正とみられるため割り戻した")
                for j in range(i):
                    if merged[j].eps is not None:
                        merged[j].eps /= split
                    if merged[j].bps is not None:
                        merged[j].bps /= split

    missing_shares = sum(1 for p in merged if not p.shares)
    if missing_shares:
        notes.append(f"発行済株式数が取れない期が {missing_shares} 期あり、分割の検出が不完全な可能性")
    for p in merged:
        if p.months is not None and p.months < 12:
            notes.append(f"{p.end} 期は {p.months} か月の変則決算")

    return History(periods=merged, splits=splits, notes=notes)
