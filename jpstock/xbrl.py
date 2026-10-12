"""EDINET の有価証券報告書 XBRL から「主要な経営指標等の推移」を取り出す層.

ネットワークには触れない。EDINET API からダウンロードした ZIP（type=1）や
XBRL インスタンスのバイト列を受け取り、5 期分の 1 株指標などを返す。
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional
from xml.etree import ElementTree as ET

_XBRLI = "{http://www.xbrl.org/2003/instance}"
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

# EDINET のコンテキスト ID 命名規約（例: CurrentYearDuration, Prior3YearInstant_NonConsolidatedMember）
_CTX_RE = re.compile(
    r"^(?:CurrentYear|Prior(?P<n>[1-9])Year)(?P<kind>Duration|Instant)(?P<nc>_NonConsolidatedMember)?$"
)

# 指標ごとの要素名（jpcrp_cor）。先にある会計基準を優先する（IFRS → 米国基準 → 日本基準）。
CONSOLIDATED_METRICS: dict[str, list[str]] = {
    "eps": [
        "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
        "BasicEarningsLossPerShareUSGAAPSummaryOfBusinessResults",
        "BasicEarningsLossPerShareSummaryOfBusinessResults",
    ],
    "bps": [
        "EquityAttributableToOwnersOfParentPerShareIFRSSummaryOfBusinessResults",
        "EquityAttributableToOwnersOfParentPerShareUSGAAPSummaryOfBusinessResults",
        "ShareholdersEquityPerShareUSGAAPSummaryOfBusinessResults",
        "NetAssetsPerShareSummaryOfBusinessResults",
    ],
    "net_income": [
        "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
        "NetIncomeLossAttributableToOwnersOfParentUSGAAPSummaryOfBusinessResults",
        "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        "NetIncomeLossSummaryOfBusinessResults",
    ],
    "total_assets": [
        "TotalAssetsIFRSSummaryOfBusinessResults",
        "TotalAssetsUSGAAPSummaryOfBusinessResults",
        "TotalAssetsSummaryOfBusinessResults",
    ],
    "equity_ratio": [
        "RatioOfOwnersEquityToGrossAssetsIFRSSummaryOfBusinessResults",
        "EquityToAssetRatioUSGAAPSummaryOfBusinessResults",
        "EquityToAssetRatioSummaryOfBusinessResults",
    ],
    "roe": [
        "RateOfReturnOnEquityIFRSSummaryOfBusinessResults",
        "RateOfReturnOnEquityUSGAAPSummaryOfBusinessResults",
        "RateOfReturnOnEquitySummaryOfBusinessResults",
    ],
}

# 提出会社（個別）の表に載る指標。個別コンテキストを優先して探す。
PARENT_METRICS: dict[str, list[str]] = {
    "dps": ["DividendPaidPerShareSummaryOfBusinessResults"],
    "shares": ["TotalNumberOfIssuedSharesSummaryOfBusinessResults"],
}

# % 表示の指標（XBRL では 0.378 のような比率で格納される）
_RATIO_METRICS = {"equity_ratio", "roe"}

_DEI = {
    "SecurityCodeDEI": "sec_code",
    "FilerNameInJapaneseDEI": "name",
    "EDINETCodeDEI": "edinet_code",
    "AccountingStandardsDEI": "accounting_standard",
    "CurrentFiscalYearEndDateDEI": "fiscal_year_end",
}
_TEXT_BLOCKS = {"DividendPolicyTextBlock": "dividend_policy"}

_WANTED = (
    {name for names in CONSOLIDATED_METRICS.values() for name in names}
    | {name for names in PARENT_METRICS.values() for name in names}
    | set(_DEI)
    | set(_TEXT_BLOCKS)
)


@dataclass
class FiscalPeriod:
    """1 決算期分の値。取得できなかった項目は None."""

    end: date
    start: Optional[date] = None
    eps: Optional[float] = None
    bps: Optional[float] = None
    dps: Optional[float] = None
    net_income: Optional[float] = None
    total_assets: Optional[float] = None
    equity_ratio: Optional[float] = None  # %
    roe: Optional[float] = None  # %
    shares: Optional[float] = None  # 期末発行済株式総数（提出会社）

    @property
    def months(self) -> Optional[int]:
        """決算期の月数（変則決算の検出用）。開始日が無ければ None."""
        if self.start is None:
            return None
        return (self.end.year - self.start.year) * 12 + (self.end.month - self.start.month) + 1

    @property
    def roa(self) -> Optional[float]:
        """ROA（%）= 当期純利益 ÷ 期末総資産."""
        if self.net_income is None or not self.total_assets:
            return None
        return self.net_income / self.total_assets * 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["end"] = self.end.isoformat()
        d["start"] = self.start.isoformat() if self.start else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FiscalPeriod":
        d = dict(d)
        d["end"] = date.fromisoformat(d["end"])
        d["start"] = date.fromisoformat(d["start"]) if d.get("start") else None
        return cls(**d)


@dataclass
class AnnualReport:
    """有価証券報告書 1 通から取り出した情報（periods は古い順）."""

    doc_id: str
    edinet_code: Optional[str] = None
    sec_code: Optional[str] = None
    name: Optional[str] = None
    accounting_standard: Optional[str] = None
    consolidated: bool = True
    dividend_policy: Optional[str] = None
    periods: list[FiscalPeriod] = field(default_factory=list)

    @property
    def latest(self) -> Optional[FiscalPeriod]:
        return self.periods[-1] if self.periods else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["periods"] = [p.to_dict() for p in self.periods]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AnnualReport":
        d = dict(d)
        d["periods"] = [FiscalPeriod.from_dict(p) for p in d.get("periods", [])]
        return cls(**d)


def extract_instance(zip_bytes: bytes) -> bytes:
    """EDINET API（type=1）の ZIP から本体の XBRL インスタンスを取り出す."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [
            n for n in zf.namelist()
            if re.search(r"XBRL/PublicDoc/[^/]+\.xbrl$", n)
        ]
        if not names:
            raise ValueError("ZIP 内に PublicDoc の XBRL インスタンスが見つかりません")
        # 有価証券報告書（asr）の本体を優先
        names.sort(key=lambda n: (0 if "jpcrp" in n and "-asr-" in n else 1, n))
        return zf.read(names[0])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_instance(xbrl: bytes) -> tuple[dict[str, dict[str, str]], dict[str, tuple[Optional[date], date]]]:
    """XBRL インスタンスを読み、必要な要素の値とコンテキストを返す.

    戻り値:
      facts:    {要素のローカル名: {contextRef: 値の文字列}}
      contexts: {コンテキストID: (開始日 or None, 終了日/時点)}
    """
    facts: dict[str, dict[str, str]] = {}
    contexts: dict[str, tuple[Optional[date], date]] = {}

    for _, elem in ET.iterparse(io.BytesIO(xbrl), events=("end",)):
        tag = elem.tag
        if tag == f"{_XBRLI}context":
            ctx_id = elem.get("id", "")
            start = elem.findtext(f"{_XBRLI}period/{_XBRLI}startDate")
            end = elem.findtext(f"{_XBRLI}period/{_XBRLI}endDate")
            instant = elem.findtext(f"{_XBRLI}period/{_XBRLI}instant")
            try:
                if instant:
                    contexts[ctx_id] = (None, date.fromisoformat(instant.strip()))
                elif end:
                    contexts[ctx_id] = (
                        date.fromisoformat(start.strip()) if start else None,
                        date.fromisoformat(end.strip()),
                    )
            except ValueError:
                pass
            elem.clear()
            continue

        ctx_ref = elem.get("contextRef")
        if ctx_ref is not None:
            name = _local(tag)
            if name in _WANTED and elem.get(_XSI_NIL) != "true" and elem.text is not None:
                facts.setdefault(name, {})[ctx_ref] = elem.text.strip()
            elem.clear()

    return facts, contexts


def _to_float(text: Optional[str]) -> Optional[float]:
    if text is None or text == "":
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def html_to_text(raw: str) -> str:
    """テキストブロック（HTML 断片）を素のテキストにする."""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _periods_in(facts: dict[str, dict[str, str]]) -> set[int]:
    idx: set[int] = set()
    for names in list(CONSOLIDATED_METRICS.values()) + list(PARENT_METRICS.values()):
        for name in names:
            for ctx in facts.get(name, {}):
                m = _CTX_RE.match(ctx)
                if m:
                    idx.add(int(m.group("n") or 0))
    return idx


def _pick(facts, names: list[str], idx: int, kind: str, nonconsolidated: bool) -> Optional[float]:
    prefix = "CurrentYear" if idx == 0 else f"Prior{idx}Year"
    ctx = f"{prefix}{kind}" + ("_NonConsolidatedMember" if nonconsolidated else "")
    for name in names:
        value = _to_float(facts.get(name, {}).get(ctx))
        if value is not None:
            return value
    return None


_KIND = {
    "eps": "Duration", "net_income": "Duration", "roe": "Duration", "dps": "Duration",
    "bps": "Instant", "total_assets": "Instant", "equity_ratio": "Instant", "shares": "Instant",
}


def build_report(
    facts: dict[str, dict[str, str]],
    contexts: dict[str, tuple[Optional[date], date]],
    doc_id: str,
) -> AnnualReport:
    """parse_instance の結果から AnnualReport を組み立てる."""
    report = AnnualReport(doc_id=doc_id)
    for elem_name, attr in _DEI.items():
        values = facts.get(elem_name)
        if values:
            setattr(report, attr, next(iter(values.values())))
    for elem_name, attr in _TEXT_BLOCKS.items():
        values = facts.get(elem_name)
        if values:
            setattr(report, attr, html_to_text(next(iter(values.values()))))

    # 連結の値が 1 つでもあれば連結ベース、無ければ個別ベース（連結財務諸表を作らない会社）
    has_consolidated = any(
        _CTX_RE.match(ctx) and not ctx.endswith("_NonConsolidatedMember")
        for name in CONSOLIDATED_METRICS["eps"] + CONSOLIDATED_METRICS["bps"]
        for ctx in facts.get(name, {})
    )
    report.consolidated = has_consolidated

    for idx in sorted(_periods_in(facts), reverse=True):  # 古い期（Prior4）から
        prefix = "CurrentYear" if idx == 0 else f"Prior{idx}Year"
        span = None
        for suffix in ("", "_NonConsolidatedMember"):
            span = contexts.get(f"{prefix}Duration{suffix}")
            if span:
                break
        end = span[1] if span else None
        start = span[0] if span else None
        if end is None:
            inst = contexts.get(f"{prefix}Instant") or contexts.get(f"{prefix}Instant_NonConsolidatedMember")
            end = inst[1] if inst else None
        if end is None:
            continue

        period = FiscalPeriod(end=end, start=start)
        for metric, names in CONSOLIDATED_METRICS.items():
            value = _pick(facts, names, idx, _KIND[metric], nonconsolidated=not has_consolidated)
            if value is not None and metric in _RATIO_METRICS and abs(value) <= 1.5:
                value *= 100.0
            setattr(period, metric, value)
        for metric, names in PARENT_METRICS.items():
            value = _pick(facts, names, idx, _KIND[metric], nonconsolidated=True)
            if value is None:
                value = _pick(facts, names, idx, _KIND[metric], nonconsolidated=False)
            setattr(period, metric, value)
        report.periods.append(period)

    report.periods.sort(key=lambda p: p.end)
    return report


def report_from_zip(zip_bytes: bytes, doc_id: str) -> AnnualReport:
    """EDINET API の ZIP（type=1）から AnnualReport を作る."""
    facts, contexts = parse_instance(extract_instance(zip_bytes))
    return build_report(facts, contexts, doc_id)
