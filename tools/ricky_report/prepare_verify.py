"""エージェントに確かめてもらう銘柄の入力 JSON（passers_N.json・fragile_N.json）を作る.

    python tools/ricky_report/prepare_verify.py results/full work/verify \
        [--only-new research/data/2026-10-13/passers.json] [--batch 8]

- passers_N.json: 通過銘柄（--only-new を付けると、前回の passers.json に無い銘柄だけ）。
  数値・10期の系列・スクリプトの注記・有報の配当政策の本文が入る。workflows/verify.js が読む。
- fragile_N.json: 第2段階で落ちた銘柄のうち、分割・併合・変則決算・会計基準の変更・報告書の
  つなぎ目などの調整が不合格理由に関係しうるもの（調整の誤りで落ちていないかを確かめる）。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

# 分割・併合の検出や割り戻し、つなぎ目のずれ、変則決算、会計基準の変更、個別の値、無配とみなした期の注記
ADJUST_WORDS = ("を検出", "割り戻した", "ずれる", "変則決算", "会計基準が", "個別の値", "無配とみなした")


def stock_entry(r: dict, s: dict) -> dict:
    return {
        "code": r["コード"], "name": r["銘柄名"], "industry": r["業種"], "status": r["判定"],
        "latest_period_end": r["直近決算期末"], "price": r["株価"], "price_date": r["株価日付"],
        "PER_actual": r["PER(実績)"], "PBR": r["PBR"], "ROE_yuho": r["ROE"], "ROA": r["ROA"],
        "dividend_yield_actual": r["配当利回り(実績)"], "DPS_actual_current_share_basis": r["1株配当(実績)"],
        "equity_ratio": r["自己資本比率"], "market_cap_oku": r["時価総額(億円)"],
        "EPS_9_periods_ago": r["EPS 9期前"], "EPS_latest": r["EPS 直近"], "EPS_ratio": r["EPS倍率"],
        "BPS_9_periods_ago": r["BPS 9期前"], "BPS_latest": r["BPS 直近"], "BPS_growth": r["BPS伸び率"],
        "BPS_increase_count": r["BPS連続増加回数"], "dividend_cut_periods": r["減配期"],
        "loss_periods": r["赤字期"], "BPS_decrease_periods": r["BPS減少期"],
        "stage2_failures": r["第2段階 不合格項目"],
        "series_10_periods": [{k: p[k] for k in ("end", "eps", "bps", "dps", "months")} for p in s["periods"][-10:]],
        "script_notes": s.get("notes", []),
        "yuho_dividend_policy_excerpt": s.get("dividend_policy", "")[:1500],
        "yuho_flags": {"累進の記載": bool(r["累進"]), "DOEの記載": bool(r["DOE"]), "DOE数値": r["DOE数値"]},
        "yuho_doc_id": r["有報docID"],
    }


def fragile(r: dict, s: dict) -> bool:
    """調整が不合格理由に関係しうる第2段階の不通過（2026-10-13 は 22 銘柄を確かめ、2 銘柄が誤りだった）.

    調整の注記があり、不合格理由が「EPS 2倍未達（1.0倍以上。分割の調整漏れなら倍率が数倍ずれる）・
    BPS 減少 2 回まで・減配 2 回」だけのもの。赤字・無配転落は調整では変わりにくいので除く。
    """
    if r["判定"] != "第2段階 不通過" or not any(w in " ".join(s.get("notes", [])) for w in ADJUST_WORDS):
        return False
    for f in r["第2段階 不合格項目"].split(" / "):
        if f in ("EPS赤字あり", "無配転落あり"):
            return False
        if f == "EPS 2倍未達":
            try:
                if float(r["EPS倍率"]) < 1.0:
                    return False
            except ValueError:
                return False
        elif f == "BPS減少あり" and len(r["BPS減少期"].split()) > 2:
            return False
        elif f.startswith("減配") and f != "減配2回":
            return False
    return True


def write_batches(items: list[dict], out: Path, prefix: str, size: int) -> int:
    for i in range(0, len(items), size):
        (out / f"{prefix}_{i // size}.json").write_text(
            json.dumps(items[i:i + size], ensure_ascii=False, indent=1), encoding="utf-8")
    return (len(items) + size - 1) // size


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("results")
    p.add_argument("out")
    p.add_argument("--only-new", help="前回の passers.json。そこに無い通過銘柄だけを調べる")
    p.add_argument("--batch", type=int, default=8)
    args = p.parse_args()

    res, out = Path(args.results), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = {r["コード"]: r for r in csv.DictReader(open(max(res.glob("ricky_all_*.csv")), encoding="utf-8-sig"))}
    series = json.loads((res / "series.json").read_text(encoding="utf-8"))
    known = set(json.loads(Path(args.only_new).read_text(encoding="utf-8"))["stocks"]) if args.only_new else set()

    passers = [stock_entry(r, series[c]) for c, r in rows.items()
               if r["判定"] == "通過" and c in series and c not in known]
    fragiles = [stock_entry(r, series[c]) for c, r in rows.items() if c in series and fragile(r, series[c])]
    nb = write_batches(passers, out, "passers", args.batch)
    nf = write_batches(fragiles, out, "fragile", args.batch)
    print(f"passers {len(passers)} 銘柄 → {nb} バッチ、fragile {len(fragiles)} 銘柄 → {nf} バッチ（{out}）")
    print("workflows/verify.js に args = {dir: '<この出力先の絶対パス>', passers: [0..], fragile: [0..]} を渡す")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
