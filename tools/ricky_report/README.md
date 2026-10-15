---
title: tools/ricky_report の道具
date: 2026-10-13
tags: [ricky-screening, tools]
---

# tools/ricky_report の道具

Ricky流スクリーニングを全上場会社で回し、確かめ、レポートと Obsidian のノートにするためのスクリプト。使う順番と手順は [次回の進め方](../../research/next-run.md)。リポジトリの根元から実行する。

| 順 | ファイル | すること |
|---|---|---|
| 1 | `run_all.py` | 全上場会社で判定し、`results/full/` に CSV・Markdown・`series.json`（10期の系列・注記・有報の配当政策）を出す。`--as-of` は実行する日にする |
| 2 | `diff_passers.py` | 前回の `research/data/<日付>/passers.json` と比べ、新しく通過・続けて通過（新しい有報と配当政策の記載の変化）・脱落を出す（前回は `prev_passers.py` が自動で選ぶ） |
| 3 | `scan_anomalies.py` | 10期の系列から、分割・併合の調整漏れを疑う飛び（BPS の 0.7 倍以下・1.6 倍以上など）を出す。確かめた結果は `mark_checked.py` で `checked.json` の `anomalies` に書く |
| 4 | `prepare_verify.py` | エージェントに確かめてもらう銘柄の入力（`passers_N.json`・`fragile_N.json`・`selected.json`）を作る。`--only-new`・`--skip-checked` で確認済みの銘柄を除く（`--only-new --no-recheck-updated` で新しく通過した銘柄だけ。月次は通過したすべての銘柄なので `--only-new` を付けない） |
| 5 | `workflows/verify.js` | Workflow ツールで実行。通過銘柄を調査担当と反証役が、判定が変わりうる不通過銘柄を監査担当が、有報の原本で確かめる |
| 6 | `collect_verify.py` | ワークフローの journal.jsonl から結果を集め、`research/data/<日付>/verify.json` と `checked.json` にする |
| 7 | `assemble.py`（`build_tables.py` を使う） | テンプレート（`report_template.tmpl` を今回のフォルダに写したもの）に表と文章のパーツを入れて、レポートを作る。表記（labels.json）の引き継ぎ・`null` での取り消し・DOE の扱いは `build_tables.py` の冒頭 |
| 8 | `make_notes.py` | `research/stocks/` の銘柄ノートと一覧、`passers.json` を書く（ノートの「メモ」の欄と、手で足したプロパティ・タグは残す） |
| — | `run_day.py` | 今日、月次の判定を始めるかを決める（実行日は毎月14日、休業日ならその前の営業日。失敗した月は16日まで取り直す）。「run 基準日」か「skip」 |
| — | `cache_sync.py` | 有報のキャッシュをブランチ `claude/data-cache` に圧縮して保存・復元する（古いデータと、第1段階を通らない会社の古い有報は消す） |
| — | `mark_checked.py` | 調整漏れの洗い出しで出た銘柄を確かめた結果を `checked.json` の `anomalies` に書く |
| — | `prev_passers.py` | 「前回」の `passers.json`（基準日より前で、決算期の入ったいちばん新しいもの）を選ぶ。diff_passers・prepare_verify・monthly_summary が使う |
| — | `monthly_summary.py` | 月次の判定の要約（`research/runs/<日付>.md`）を書く。前回との変化・境界に近い銘柄・未調査の銘柄など |
| — | `usage.py` | 会話記録から、モデルの呼び出し回数と読み込んだトークンを数える（[費用と時間の目安](../../research/costs.md) の記録用） |

## 作り直しの確認

2026-10-13 の作業環境（`results/full/` と同じ日の株価のキャッシュが残っている環境）では、次で今のレポートと同じものが作れることを `diff` で確かめた。新しく clone した環境では `results/` が無く、`run_all.py` を別の日に実行すると株価が変わるので、同じものにはならない。

```bash
python tools/ricky_report/assemble.py --results results/full \
  --verify research/data/*/verify.json --labels research/data/*/labels.json \
  --parts research/data/2026-10-13/parts --as-of 2026-10-13 --out /tmp/check.md
diff /tmp/check.md research/ricky_screening_full_2026-10-13.md
```

Related: [次回の進め方](../../research/next-run.md) · [調査ノートの入口](../../research/INDEX.md) · [README](../../README.md)
