"""調整漏れの洗い出し（scan_anomalies.py）で出た銘柄を有報で確かめた結果を、checked.json の anomalies に書く.

    python tools/ricky_report/mark_checked.py research/data/<今日>/checked.json --results results/full \
        --code 7095 --note "上場前の分割の調整漏れ。有報の値と系列が一致することを確かめた"

- 銘柄名・直近の決算期・今回の判定は、判定結果の CSV から入れる。note には何を確かめ、どうだったかを書く。
- 同じ銘柄・同じ決算期は、monthly_summary.py の「調整漏れの洗い出しで新しく出た銘柄」から次回以降は外れる
  （決算期が変われば、また出る）。
- checked.json が無ければ作る（collect_verify.py --selected が後から fragile を足しても消えない）。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("checked", help="research/data/<今日>/checked.json")
    p.add_argument("--results", default="results/full")
    p.add_argument("--code", required=True, nargs="+", help="確かめた銘柄コード（同じ note で複数可）")
    p.add_argument("--note", required=True, help="確かめた内容と結果")
    a = p.parse_args()
    rows = {r["コード"]: r for r in csv.DictReader(open(max(Path(a.results).glob("ricky_all_*.csv")), encoding="utf-8-sig"))}
    path = Path(a.checked)
    checked = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"run": path.parent.name, "fragile": {}}
    checked.setdefault("anomalies", {})
    for code in a.code:
        r = rows.get(code)
        if r is None:
            raise SystemExit(f"{code} は判定結果に無い")
        checked["anomalies"][code] = {"name": r["銘柄名"], "latest_period_end": r["直近決算期末"], "status": r["判定"],
                                      "note": a.note}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checked, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"checked.json: 洗い出しの確認 {len(checked['anomalies'])} 銘柄 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
