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

# キャッシュする要素の範囲（_keep_fact）を変えたら上げる（古い版のキャッシュは取り直す）
FACTS_VERSION = 1

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
        "EquityToAssetRatioIFRSSummaryOfBusinessResults",
        "EquityToAssetRatioUSGAAPSummaryOfBusinessResults",
        "EquityToAssetRatioSummaryOfBusinessResults",
    ],
    "roe": [
        "RateOfReturnOnEquityIFRSSummaryOfBusinessResults",
        "RateOfReturnOnEquityUSGAAPSummaryOfBusinessResults",
        "RateOfReturnOnEquitySummaryOfBusinessResults",
    ],
    # BPS が載っていない報告書（トヨタの IFRS など）で BPS を求めるのに使う
    "owners_equity": ["EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults"],
}

# 提出会社（個別）の表に載る指標。個別コンテキストを優先して探す。
PARENT_METRICS: dict[str, list[str]] = {
    # 種類株式のある会社（東京製綱など）は普通株式の要素で載せる
    "dps": ["DividendPaidPerShareSummaryOfBusinessResults", "DividendPaidPerShareCommonStockSummaryOfBusinessResults"],
    "interim_dps": ["InterimDividendPaidPerShareSummaryOfBusinessResults",
                    "InterimDividendPaidPerShareCommonStockSummaryOfBusinessResults"],
    "shares": ["TotalNumberOfIssuedSharesSummaryOfBusinessResults",
               "CommonStocksTotalNumberOfIssuedSharesSummaryOfBusinessResults"],
    # 配当性向と提出会社の EPS。1 株配当 ÷ 配当性向 で、その配当がどの株数の基準かを確かめるのに使う
    "payout": ["PayoutRatioSummaryOfBusinessResults"],
    "eps_parent": ["BasicEarningsLossPerShareSummaryOfBusinessResults"],
}

# % 表示の指標（XBRL では 0.378 のような小数で格納されるので 100 倍する）
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
    interim_dps: Optional[float] = None  # 1 株配当のうち中間配当
    owners_equity: Optional[float] = None  # 親会社の所有者に帰属する持分（IFRS。BPS が無いときに使う）
    bps_source: Optional[str] = None  # BPS を表から直接取れなかったときの取り方
    dps_assumed_zero: bool = False  # 1 株配当の欄が空（「－」）なので無配とみなした
    payout: Optional[float] = None  # 配当性向（提出会社、0.355 のような小数）
    eps_parent: Optional[float] = None  # 提出会社の 1 株当たり当期純利益（配当性向の計算の基準）
    nonconsolidated: bool = False  # 個別の値（連結財務諸表を作らない会社の報告書、または連結の欄が空の期）
    standard: Optional[str] = None  # EPS を取った要素の会計基準（JP / IFRS / US）

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
    filing_date: Optional[date] = None  # 提出日（XBRL の FilingDateInstant）
    dividend_policy: Optional[str] = None
    periods: list[FiscalPeriod] = field(default_factory=list)

    @property
    def latest(self) -> Optional[FiscalPeriod]:
        return self.periods[-1] if self.periods else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["periods"] = [p.to_dict() for p in self.periods]
        d["filing_date"] = self.filing_date.isoformat() if self.filing_date else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AnnualReport":
        d = dict(d)
        d["periods"] = [FiscalPeriod.from_dict(p) for p in d.get("periods", [])]
        d["filing_date"] = date.fromisoformat(d["filing_date"]) if d.get("filing_date") else None
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


def _keep_fact(name: str) -> bool:
    """キャッシュに残す要素: 主要な経営指標等の推移の全項目・DEI・配当政策など.

    取り出し方（build_report）を後で変えても、書類を取り直さずにキャッシュから計算し直せるよう、
    いま使っていない項目も含めて「主要な経営指標等の推移」はすべて残す。
    """
    return name in _WANTED or name.endswith("SummaryOfBusinessResults") or name.endswith("DEI")


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
            if _keep_fact(name) and elem.get(_XSI_NIL) != "true" and elem.text is not None:
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


def _pick_named(facts, names: list[str], idx: int, kind: str, nonconsolidated: bool) -> tuple[Optional[float], Optional[str]]:
    prefix = "CurrentYear" if idx == 0 else f"Prior{idx}Year"
    ctx = f"{prefix}{kind}" + ("_NonConsolidatedMember" if nonconsolidated else "")
    for name in names:
        value = _to_float(facts.get(name, {}).get(ctx))
        if value is not None:
            return value, name
    return None, None


def _pick(facts, names: list[str], idx: int, kind: str, nonconsolidated: bool) -> Optional[float]:
    return _pick_named(facts, names, idx, kind, nonconsolidated)[0]


def _standard_of(element: Optional[str]) -> Optional[str]:
    if element is None:
        return None
    if "IFRS" in element:
        return "IFRS"
    if "USGAAP" in element:
        return "US"
    return "JP"


_KIND = {
    "eps": "Duration", "net_income": "Duration", "roe": "Duration", "dps": "Duration", "interim_dps": "Duration",
    "payout": "Duration", "eps_parent": "Duration",
    "bps": "Instant", "total_assets": "Instant", "equity_ratio": "Instant", "shares": "Instant",
    "owners_equity": "Instant",
}


def _fill_missing_bps(period: FiscalPeriod, facts, idx: int, nonconsolidated: bool) -> None:
    """BPS が BPS の要素に無い期を補う.

    IFRS の会社の多く（トヨタ・日本航空・カヤバなど）は、1 株当たり親会社所有者帰属持分を
    EquityToAssetRatioIFRS という比率のような名前の要素で載せている。比率としてあり得ない値（1.5 超）
    なら BPS とみなす（親会社所有者帰属持分 ÷（純利益 ÷ EPS）の概算と 0.5〜2 倍の範囲で確かめる）。
    それも無ければ概算を使う。概算は期中に株式数が大きく変わった年は 10% ほどずれる。
    """
    if period.bps is not None:
        return
    estimate = None
    if period.owners_equity and period.eps and period.net_income and period.net_income / period.eps > 0:
        estimate = period.owners_equity / (period.net_income / period.eps)
    for name in CONSOLIDATED_METRICS["equity_ratio"]:
        value = _pick(facts, [name], idx, "Instant", nonconsolidated)
        if value is not None and value > 1.5 and (estimate is None or 0.5 <= value / estimate <= 2):
            period.bps, period.bps_source = value, f"{name.replace('SummaryOfBusinessResults', '')} の要素の値"
            return
    if estimate is not None:
        period.bps, period.bps_source = estimate, "親会社所有者帰属持分÷(純利益÷EPS)の概算"


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
    filing = contexts.get("FilingDateInstant")
    report.filing_date = filing[1] if filing else None

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

        # 連結決算を始める前の期などは連結の欄が空（nil）なので、その期だけ個別の値を使う
        use_parent = not has_consolidated or all(
            _pick(facts, CONSOLIDATED_METRICS[m], idx, _KIND[m], nonconsolidated=False) is None
            for m in ("eps", "bps")
        )
        period = FiscalPeriod(end=end, start=start, nonconsolidated=use_parent)
        # 会計基準を移行した年は同じ期に複数の基準の値が載るので、EPS と同じ基準の要素を優先する
        _, eps_element = _pick_named(facts, CONSOLIDATED_METRICS["eps"], idx, "Duration", use_parent)
        standard = _standard_of(eps_element)
        deferred_bps: list[str] = []
        for metric, names in CONSOLIDATED_METRICS.items():
            if standard:
                names = sorted(names, key=lambda n: _standard_of(n) != standard)
            if metric == "bps" and standard:
                # 別の基準の BPS は、同じ基準の持分から求められないときだけ使う（下の _fill_missing_bps の後）
                deferred_bps = [n for n in names if _standard_of(n) != standard]
                names = [n for n in names if _standard_of(n) == standard]
            if metric == "equity_ratio":
                # 比率としてあり得ない値（1.5 超。1 株当たりの金額などの誤り）は飛ばして次の要素を見る
                value = next((v for v in (_pick(facts, [n], idx, "Instant", use_parent) for n in names)
                              if v is not None and abs(v) <= 1.5), None)
                element = None
            else:
                value, element = _pick_named(facts, names, idx, _KIND[metric], nonconsolidated=use_parent)
            if value is not None and metric in _RATIO_METRICS:
                value *= 100.0  # EDINET の % 項目は 0.378 のような小数で入っている
            setattr(period, metric, value)
        period.standard = standard
        for metric, names in PARENT_METRICS.items():
            value = _pick(facts, names, idx, _KIND[metric], nonconsolidated=True)
            if value is None:
                value = _pick(facts, names, idx, _KIND[metric], nonconsolidated=False)
            setattr(period, metric, value)
        _fill_missing_bps(period, facts, idx, use_parent)
        if period.bps is None and deferred_bps:
            value, element = _pick_named(facts, deferred_bps, idx, "Instant", nonconsolidated=use_parent)
            if value is not None:
                period.bps = value
                period.bps_source = f"EPS と別の会計基準（{_standard_of(element)}）の BPS"
        if period.standard is None:
            _, bps_element = _pick_named(facts, CONSOLIDATED_METRICS["bps"], idx, "Instant", use_parent)
            period.standard = _standard_of(bps_element)
        report.periods.append(period)

    report.periods.sort(key=lambda p: p.end)
    # 無配の期は 1 株配当の欄が「－」（XBRL では nil）になる。同じ報告書の他の期に配当があれば無配とみなす
    if any(p.dps is not None for p in report.periods):
        for p in report.periods:
            if p.dps is None:
                p.dps, p.dps_assumed_zero = 0.0, True
    return report


def report_from_zip(zip_bytes: bytes, doc_id: str) -> AnnualReport:
    """EDINET API の ZIP（type=1）から AnnualReport を作る."""
    facts, contexts = parse_instance(extract_instance(zip_bytes))
    return build_report(facts, contexts, doc_id)


def facts_to_dict(facts: dict[str, dict[str, str]], contexts: dict[str, tuple[Optional[date], date]]) -> dict:
    """parse_instance の結果を JSON にできる形にする（使うコンテキストだけ残す）."""
    used = {ctx for values in facts.values() for ctx in values}
    keep = {c: v for c, v in contexts.items() if c in used and (_CTX_RE.match(c) or c == "FilingDateInstant")}
    keep.setdefault("FilingDateInstant", contexts.get("FilingDateInstant"))
    return {
        "facts_version": FACTS_VERSION,
        "facts": {name: {c: v for c, v in values.items() if c in keep} for name, values in facts.items()},
        "contexts": {c: [v[0].isoformat() if v[0] else None, v[1].isoformat()] for c, v in keep.items() if v},
    }


def facts_from_dict(d: dict) -> tuple[dict[str, dict[str, str]], dict[str, tuple[Optional[date], date]]]:
    contexts = {
        c: (date.fromisoformat(v[0]) if v[0] else None, date.fromisoformat(v[1]))
        for c, v in d.get("contexts", {}).items()
    }
    return d.get("facts", {}), contexts
