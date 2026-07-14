"""株価ヒストリカルチャートを PNG に描画する層."""

from __future__ import annotations

from typing import Iterable

from .models import StockSummary

# 日本語表示に使えるフォント候補（環境にあるものを優先的に使う）
_JP_FONT_CANDIDATES = [
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "IPAGothic",
    "IPAPGothic",
    "TakaoGothic",
    "VL Gothic",
    "Yu Gothic",
    "Meiryo",
    "MS Gothic",
    "Hiragino Sans",
]


def _configure_japanese_font() -> bool:
    """利用可能な日本語フォントを matplotlib に設定する.

    設定できれば True、日本語フォントが見つからなければ False を返す。
    """
    import matplotlib
    import matplotlib.font_manager as fm

    available = {f.name for f in fm.fontManager.ttflist}
    for name in _JP_FONT_CANDIDATES:
        if name in available:
            matplotlib.rcParams["font.family"] = name
            matplotlib.rcParams["axes.unicode_minus"] = False
            return True
    return False


def save_price_chart(summaries: Iterable[StockSummary], path: str) -> str:
    """複数銘柄の終値推移を 1 枚の折れ線チャートに描画して保存する.

    history を持たない銘柄はスキップする。
    戻り値は保存したファイルパス。
    """
    import matplotlib

    matplotlib.use("Agg")  # ヘッドレス環境用
    has_jp = _configure_japanese_font()
    import matplotlib.pyplot as plt

    summaries = [s for s in summaries if s.ok and s.history is not None and not s.history.empty]
    if not summaries:
        raise ValueError("チャートに描画できるヒストリカルデータがありません")

    fig, ax = plt.subplots(figsize=(10, 6))
    for s in summaries:
        hist = s.history
        # 日本語フォントが無い環境では文字化けを避けるためコードのみを凡例に使う
        label = f"{s.name} ({s.code})" if (has_jp and s.name) else s.code
        ax.plot(hist.index, hist["Close"], label=label, linewidth=1.6)

    if has_jp:
        ax.set_title("株価推移（終値）")
        ax.set_xlabel("日付")
        ax.set_ylabel("株価")
    else:
        ax.set_title("Price Trend (Close)")
        ax.set_xlabel("Date")
        ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
