"""コマンドラインインターフェース."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import fetcher, formatter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jpstock",
        description="日本株の株価・投資指標・企業情報をまとめて取得・表示するツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  jpstock 7203 6758 9984            # トヨタ・ソニー・ソフトバンクGを表で表示\n"
            "  jpstock 7203 --format markdown    # Markdown レポートで出力\n"
            "  jpstock 7203 6758 --format csv -o report.csv\n"
            "  jpstock 7203 6758 --chart price.png\n"
        ),
    )
    parser.add_argument("tickers", nargs="+", help="銘柄コード（例: 7203, 6758.T, ^N225）")
    parser.add_argument(
        "-f", "--format",
        choices=["table", "markdown", "csv"],
        default="table",
        help="出力フォーマット（既定: table）",
    )
    parser.add_argument(
        "-o", "--output",
        help="出力先ファイル。未指定なら標準出力。",
    )
    parser.add_argument(
        "--chart",
        metavar="PATH",
        help="株価推移チャートを PNG で保存するパス（例: chart.png）",
    )
    parser.add_argument(
        "-p", "--period",
        default="6mo",
        help="ヒストリカルデータ期間（yfinance 形式。例: 1mo, 6mo, 1y, 5y。既定: 6mo）",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def render(summaries, fmt: str) -> str:
    if fmt == "csv":
        return formatter.render_csv(summaries)
    if fmt == "markdown":
        return formatter.render_markdown(summaries)
    # table は端末描画のため別扱い（render では扱わない）
    return formatter.render_plain_table(summaries)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        summaries = fetcher.fetch_many(args.tickers, period=args.period)
    except Exception as exc:  # noqa: BLE001
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    # チャート出力
    if args.chart:
        try:
            from . import chart

            path = chart.save_price_chart(summaries, args.chart)
            print(f"チャートを保存しました: {path}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"チャート生成に失敗しました: {exc}", file=sys.stderr)

    # 本体出力
    if args.format == "table" and not args.output:
        formatter.print_table(summaries)
    else:
        text = render(summaries, args.format)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"出力しました: {args.output}", file=sys.stderr)
        else:
            print(text)

    # 全銘柄取得失敗なら異常終了
    if all(not s.ok for s in summaries):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
