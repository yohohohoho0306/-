"""第2段階を判定した銘柄の10期の系列から、分割・併合の調整漏れを疑う値を洗い出す.

    python tools/ricky_report/scan_anomalies.py results/full

BPS が前期の 0.7 倍未満・1.6 倍超に飛ぶ期、BPS 伸び率・EPS 倍率が極端な銘柄を出す。
2026-10-13 の実行では、この洗い出しで MacbeePlanet（上場前の分割が直っていない期）が見つかった。
出てきた銘柄は、有報の原本（純利益・純資産・株式数）で実際の増減か調整漏れかを確かめる。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def find(out: Path) -> tuple[list[dict], str]:
    """洗い出しの結果（銘柄ごとの dict）と CSV のファイル名を返す."""
    csv_path = max(out.glob("ricky_all_*.csv"))
    rows = {r["コード"]: r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))}
    series = json.loads((out / "series.json").read_text(encoding="utf-8"))
    hits = []
    for code, r in rows.items():
        if r["判定"] not in ("通過", "第2段階 不通過", "第2段階 判定不能") or code not in series:
            continue
        ps = series[code]["periods"]
        jumps = [f"{ps[i]['end'][:7]}: {ps[i]['bps'] / ps[i - 1]['bps']:.2f}倍"
                 for i in range(1, len(ps))
                 if ps[i - 1]["bps"] and ps[i]["bps"] and not 0.7 < ps[i]["bps"] / ps[i - 1]["bps"] < 1.6]
        try:
            growth, ratio = float(r["BPS伸び率"] or "nan"), float(r["EPS倍率"] or "nan")
        except ValueError:
            growth = ratio = float("nan")
        if jumps or growth < 0.6 or growth > 6 or ratio < 0.3 or ratio > 15:
            hits.append({"code": code, "name": r["銘柄名"], "status": r["判定"], "latest_period_end": r["直近決算期末"],
                         "bps_growth": r["BPS伸び率"], "eps_ratio": r["EPS倍率"],
                         "failures": r["第2段階 不合格項目"], "jumps": jumps})
    return hits, csv_path.name


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "results/full")
    hits, name = find(out)
    for h in hits:
        print(f"{h['code']} {h['name']} [{h['status']}] BPS伸び率 {h['bps_growth']} EPS倍率 {h['eps_ratio']} "
              f"不合格 {h['failures'] or '-'} | BPS の飛び: {', '.join(h['jumps']) or 'なし'}")
    print(f"{len(hits)} 銘柄（{name}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
