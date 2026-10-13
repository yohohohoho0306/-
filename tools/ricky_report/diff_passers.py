"""前回の通過銘柄（research/data/<日付>/passers.json）と今回の判定結果を比べる.

    python tools/ricky_report/diff_passers.py results/full research/data/2026-10-13/passers.json

「新しく通過」「続けて通過」「脱落（今回の判定）」を出す。新しく通過した銘柄だけ、
テーマ性・配当方針を調べ直せばよい（続けて通過した銘柄は前回の調査を再利用し、
新しい有報で配当方針が変わっていないかだけ確かめる）。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> int:
    out, prev_path = Path(sys.argv[1]), Path(sys.argv[2])
    csv_path = max(out.glob("ricky_all_*.csv"))
    rows = {r["コード"]: r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))}
    prev = json.loads(prev_path.read_text(encoding="utf-8"))["stocks"]
    now = {c for c, r in rows.items() if r["判定"] == "通過"}
    before = set(prev)
    print(f"今回 {csv_path.name}: 通過 {len(now)}／前回 {prev_path}: 通過 {len(before)}")
    print(f"\n## 新しく通過（{len(now - before)}）— テーマ性・配当方針を調べる")
    for c in sorted(now - before):
        print(f"- {c} {rows[c]['銘柄名']}（{rows[c]['業種']}）")
    print(f"\n## 続けて通過（{len(now & before)}）— 前回の調査を再利用。新しい有報が出ていれば配当方針だけ確かめる")
    for c in sorted(now & before):
        new_fy = rows[c]["直近決算期末"] != prev[c]["latest_period_end"]
        print(f"- {c} {rows[c]['銘柄名']}" + ("（新しい有報あり: " + rows[c]["直近決算期末"] + "）" if new_fy else ""))
    print(f"\n## 脱落（{len(before - now)}）— 今回の判定と落ちた条件")
    for c in sorted(before - now):
        r = rows.get(c)
        if r is None:
            print(f"- {c} {prev[c]['name']}: 今回の対象に無い（上場廃止など）")
            continue
        why = r["第1段階 不合格項目"] or r["第2段階 不合格項目"] or r["第1段階 未確認項目"] or r["第2段階 未確認項目"]
        print(f"- {c} {r['銘柄名']}: {r['判定']}（{why}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
