"""前回の通過銘柄（research/data/<日付>/passers.json）と今回の判定結果を比べる.

    python tools/ricky_report/diff_passers.py results/full [research/data/2026-10-13/passers.json]

前回の passers.json を省くと、判定の基準日より前で決算期の入ったいちばん新しいものを使う（prev_passers.py）。

「新しく通過」「続けて通過」「脱落（今回の判定）」を出す。新しく通過した銘柄と、続けて通過して
新しい有報が出た銘柄は、テーマ性・配当方針を調べ直す（prepare_verify.py --only-new がこの2つを選ぶ）。
新しい有報が出た銘柄には、有報の配当政策を機械的に見た記載（累進・DOE・DOE の数値）が前回と比べて
変わったかも出す（変わっていれば配当方針の表記を見直す）。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prev_passers  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1])
    csv_path = max(out.glob("ricky_all_*.csv"))
    rows = {r["コード"]: r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))}
    doc, prev_path = prev_passers.load(sys.argv[2] if len(sys.argv) > 2 else None, prev_passers.as_of_of(out))
    prev = doc["stocks"]
    now = {c for c, r in rows.items() if r["判定"] == "通過"}
    before = set(prev)
    print(f"今回 {csv_path.name}: 通過 {len(now)}／前回 {prev_path}: 通過 {len(before)}")
    print(f"\n## 新しく通過（{len(now - before)}）— テーマ性・配当方針を調べる")
    for c in sorted(now - before):
        print(f"- {c} {rows[c]['銘柄名']}（{rows[c]['業種']}）")
    print(f"\n## 続けて通過（{len(now & before)}）— 新しい有報が無ければ前回の調査を再利用。新しい有報があればテーマ性・配当方針を調べ直す")
    for c in sorted(now & before):
        r, q = rows[c], prev[c]
        line = f"- {c} {r['銘柄名']}"
        if q.get("latest_period_end") and r["直近決算期末"] != q["latest_period_end"]:
            line += f"（新しい有報あり: {r['直近決算期末']}"
            if "yuho_doe" in q:
                was = (q["yuho_progressive"], q["yuho_doe"], q["yuho_doe_value"])
                cur = (bool(r["累進"]), bool(r["DOE"]), r["DOE数値"])
                line += "。配当政策の記載: " + ("変化なし" if was == cur else
                                              f"変化あり（累進 {was[0]}→{cur[0]}、DOE {was[1]}→{cur[1]}、数値 {was[2] or '-'}→{cur[2] or '-'}）")
            line += "）"
        print(line)
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
