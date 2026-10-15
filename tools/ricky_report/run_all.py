"""全上場会社で判定し、CSV・Markdown と、第1段階を通過した銘柄の10期の系列（series.json）を出す.

    python tools/ricky_report/run_all.py --as-of 2026-10-13 --out results/full

有報は .cache/edinet、株価・分割・配当の履歴は .cache/prices にキャッシュする。株価のキャッシュは実行した日ごとの
ファイルなので、別の日には取り直す。途中で止まっても、もう一度実行すればキャッシュの続きから進む。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jpstock import screen  # noqa: E402
from jpstock.edinet import EdinetClient  # noqa: E402
from jpstock.prices import fetch_actions, fetch_prices  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as-of", required=True,
                   help="基準日 YYYY-MM-DD（有報を探す期間の終わりと出力ファイル名）。株価は実行した時点の最新の終値になるので、"
                        "実行する日（東証の取引終了後）にする。実際の株価の日付は CSV の「株価日付」の列で確かめる")
    p.add_argument("--out", default="results/full", help="出力先（既定: results/full）")
    p.add_argument("--cache-dir", default=str(ROOT / ".cache"), help="キャッシュの親フォルダ（既定: .cache）")
    p.add_argument("--sleep", type=float, default=0.5, help="EDINET API の呼び出し間隔（秒）")
    args = p.parse_args()

    as_of = date.fromisoformat(args.as_of)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir)
    client = EdinetClient(cache_dir=str(cache / "edinet"), sleep=args.sleep)
    rows = screen.run_pipeline(
        client, lambda c: fetch_prices(c, cache_dir=cache / "prices"), as_of,
        split_source=lambda c: fetch_actions(c, cache_dir=cache / "prices"),
    )
    stamp = as_of.strftime("%Y%m%d")
    screen.write_csv(rows, out / f"ricky_all_{stamp}.csv")
    (out / f"ricky_report_{stamp}.md").write_text(screen.render_markdown(rows, as_of), encoding="utf-8")

    series = {}
    for r in rows:
        if r.history is None:
            continue
        series[r.company.sec_code] = {
            "name": screen.display_name(r.company.name),
            "status": r.status,
            "periods": [{"end": str(q.end), "eps": q.eps, "bps": q.bps, "dps": q.dps, "shares": q.shares,
                         "months": q.months, "standard": q.standard, "nc": q.nonconsolidated}
                        for q in r.history.periods],
            "notes": r.notes + r.history.notes,
            # 配当方針の調べ直し（prepare_verify.py）で使う、有報の「配当政策」の本文
            "dividend_policy": (r.report.dividend_policy or "")[:3000] if r.report else "",
        }
    (out / "series.json").write_text(json.dumps(series, ensure_ascii=False), encoding="utf-8")
    print("done", sum(1 for r in rows if r.status == "通過"), "passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
