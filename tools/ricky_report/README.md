---
title: tools/ricky_report の道具
date: 2026-10-13
tags: [ricky-screening, tools]
---

# tools/ricky_report の道具

Ricky流スクリーニングを全上場会社で回し、確かめ、レポートと Obsidian のノートにするためのスクリプト。使う順番と手順は [次回の進め方](../../research/next-run.md)。リポジトリの根元から実行する。

| 順 | ファイル | すること |
|---|---|---|
| 1 | `run_all.py` | 全上場会社で判定し、`results/full/` に CSV・Markdown・`series.json`（10期の系列・注記・有報の配当政策）を出す |
| 2 | `diff_passers.py` | 前回の `research/data/<日付>/passers.json` と比べ、新しく通過・続けて通過・脱落を出す |
| 3 | `scan_anomalies.py` | 10期の系列から、分割・併合の調整漏れを疑う飛び（BPS の 0.7 倍未満・1.6 倍超など）を出す |
| 4 | `prepare_verify.py` | エージェントに確かめてもらう銘柄の入力（`passers_N.json`・`fragile_N.json`）を作る |
| 5 | `workflows/verify.js` | Workflow ツールで実行。通過銘柄を調査担当と反証役が、判定が変わりうる不通過銘柄を監査担当が、有報の原本で確かめる |
| 6 | `collect_verify.py` | ワークフローの journal.jsonl から結果を集め、`research/data/<日付>/verify.json` にする |
| 7 | `assemble.py`（`build_tables.py` を使う） | テンプレート `report_template.tmpl` に表と文章のパーツを入れて、レポートを作る |
| 8 | `make_notes.py` | `research/stocks/` の銘柄ノートと一覧、`passers.json` を書く（ノートの「メモ」の欄は残す） |

## 作り直しの確認

2026-10-13 のレポートは、同じ日のキャッシュで `run_all.py` を実行したあと、次で同じものが作れる（`diff` で差が無いことを確かめた）。

```bash
python tools/ricky_report/assemble.py --results results/full \
  --verify research/data/2026-10-13/verify.json --labels research/data/2026-10-13/labels.json \
  --parts research/data/2026-10-13/parts --as-of 2026-10-13 --out /tmp/check.md
diff /tmp/check.md research/ricky_screening_full_2026-10-13.md
```

別の日に実行すると株価が変わるので、数値は同じにならない。

Related: [次回の進め方](../../research/next-run.md) · [調査ノートの入口](../../research/INDEX.md) · [README](../../README.md)
