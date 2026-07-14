"""StockSummary を各種フォーマットで出力する層."""

from __future__ import annotations

import csv
import io
from typing import Iterable

from .models import StockSummary


# ---- 値の整形ヘルパ -------------------------------------------------------

def fmt_price(v, currency: str = "JPY") -> str:
    if v is None:
        return "-"
    if currency == "JPY":
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def fmt_num(v, digits: int = 2) -> str:
    if v is None:
        return "-"
    return f"{v:,.{digits}f}"


def fmt_pct(v, digits: int = 2) -> str:
    """比率（0.025）を % 表示（2.50%）に."""
    if v is None:
        return "-"
    return f"{v * 100:.{digits}f}%"


def fmt_signed_pct(v, digits: int = 2) -> str:
    """変化率（すでに % 値）を符号付きで表示."""
    if v is None:
        return "-"
    return f"{v:+.{digits}f}%"


def fmt_market_cap(v) -> str:
    """時価総額を兆/億単位に丸めて表示."""
    if v is None:
        return "-"
    oku = v / 1e8  # 億円
    if oku >= 10000:
        return f"{oku / 10000:,.2f} 兆円"
    return f"{oku:,.0f} 億円"


def fmt_volume(v) -> str:
    if v is None:
        return "-"
    return f"{v:,.0f}"


# ---- テキスト表（rich 未使用でも動く）------------------------------------

_FIELDS = [
    ("コード", lambda s: s.code),
    ("銘柄名", lambda s: s.name or "-"),
    ("現在値", lambda s: fmt_price(s.price, s.currency)),
    ("前日比", lambda s: fmt_price(s.change, s.currency) if s.change is not None else "-"),
    ("前日比%", lambda s: fmt_signed_pct(s.change_percent)),
    ("出来高", lambda s: fmt_volume(s.volume)),
    ("PER", lambda s: fmt_num(s.per)),
    ("PBR", lambda s: fmt_num(s.pbr)),
    ("配当利回り", lambda s: fmt_pct(s.dividend_yield)),
    ("時価総額", lambda s: fmt_market_cap(s.market_cap)),
]


def to_rows(summaries: Iterable[StockSummary]) -> tuple[list[str], list[list[str]]]:
    """ヘッダ行とデータ行のタプルを返す（テスト・CSV 共用）."""
    headers = [h for h, _ in _FIELDS]
    rows = []
    for s in summaries:
        if not s.ok:
            row = [s.code, f"[取得失敗] {s.error}"] + ["-"] * (len(_FIELDS) - 2)
        else:
            row = [getter(s) for _, getter in _FIELDS]
        rows.append(row)
    return headers, rows


def render_plain_table(summaries: Iterable[StockSummary]) -> str:
    """依存ライブラリ無しのシンプルな整列テキスト表."""
    headers, rows = to_rows(list(summaries))
    all_rows = [headers] + rows
    widths = [max(_display_width(r[i]) for r in all_rows) for i in range(len(headers))]

    def line(cells: list[str]) -> str:
        return " | ".join(_pad(c, widths[i]) for i, c in enumerate(cells))

    sep = "-+-".join("-" * w for w in widths)
    out = [line(headers), sep]
    out += [line(r) for r in rows]
    return "\n".join(out)


def _display_width(s: str) -> int:
    """全角文字を 2 幅として数える簡易実装."""
    width = 0
    for ch in s:
        width += 2 if ord(ch) > 0x1100 and _is_wide(ch) else 1
    return width


def _is_wide(ch: str) -> bool:
    o = ord(ch)
    return (
        0x1100 <= o <= 0x115F
        or 0x2E80 <= o <= 0xA4CF
        or 0xAC00 <= o <= 0xD7A3
        or 0xF900 <= o <= 0xFAFF
        or 0xFE30 <= o <= 0xFE4F
        or 0xFF00 <= o <= 0xFF60
        or 0xFFE0 <= o <= 0xFFE6
    )


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _display_width(s))


# ---- rich テーブル --------------------------------------------------------

def render_rich_table(summaries: Iterable[StockSummary]):
    """rich.Table を返す（rich が無い環境では ImportError）."""
    from rich.table import Table
    from rich import box

    summaries = list(summaries)
    table = Table(title="日本株サマリー", box=box.ROUNDED, header_style="bold cyan")
    for header, _ in _FIELDS:
        table.add_column(header, justify="right" if header not in ("コード", "銘柄名") else "left")

    for s in summaries:
        if not s.ok:
            cells = [s.code, f"[取得失敗] {s.error}"] + ["-"] * (len(_FIELDS) - 2)
            table.add_row(*cells, style="red")
            continue
        cp = s.change_percent
        color = "green" if (cp or 0) > 0 else "red" if (cp or 0) < 0 else "white"
        cells = [getter(s) for _, getter in _FIELDS]
        # 前日比・前日比% だけ色付け
        cells[3] = f"[{color}]{cells[3]}[/{color}]"
        cells[4] = f"[{color}]{cells[4]}[/{color}]"
        table.add_row(*cells)
    return table


def print_table(summaries: Iterable[StockSummary]) -> None:
    """端末に表を出力（rich があれば rich、無ければプレーン）."""
    summaries = list(summaries)
    try:
        from rich.console import Console

        Console().print(render_rich_table(summaries))
    except ImportError:
        print(render_plain_table(summaries))


# ---- CSV ------------------------------------------------------------------

def render_csv(summaries: Iterable[StockSummary]) -> str:
    headers, rows = to_rows(list(summaries))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


# ---- Markdown レポート ----------------------------------------------------

def render_markdown(summaries: Iterable[StockSummary]) -> str:
    summaries = list(summaries)
    headers, rows = to_rows(summaries)

    lines = ["# 日本株サマリーレポート", ""]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 銘柄ごとの詳細
    for s in summaries:
        if not s.ok:
            continue
        lines.append(f"## {s.name or s.code}（{s.code}）")
        if s.sector or s.industry:
            lines.append(f"- **業種**: {s.sector or '-'} / {s.industry or '-'}")
        lines.append(f"- **現在値**: {fmt_price(s.price, s.currency)} {s.currency}"
                     f"（前日比 {fmt_signed_pct(s.change_percent)}）")
        lines.append(f"- **52週レンジ**: {fmt_price(s.week52_low, s.currency)} "
                     f"〜 {fmt_price(s.week52_high, s.currency)}")
        lines.append(f"- **PER / PBR**: {fmt_num(s.per)} / {fmt_num(s.pbr)}")
        lines.append(f"- **配当利回り**: {fmt_pct(s.dividend_yield)}")
        lines.append(f"- **時価総額**: {fmt_market_cap(s.market_cap)}")
        if s.summary:
            snippet = s.summary.strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:300] + "…"
            lines.append(f"- **事業概要**: {snippet}")
        lines.append("")

    return "\n".join(lines)
