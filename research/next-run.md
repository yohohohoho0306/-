---
title: 次回の進め方
date: 2026-10-13
tags: [ricky-screening, howto]
aliases: [続行の手順]
---

# 次回の進め方

> [!NOTE]
> Claude に続きをやってもらうときは「research/next-run.md を読んで、Ricky流スクリーニングの次回分を進めて」と頼めばよい。
> このノートと [費用と時間の目安](costs.md)・[既知の問題と未確認の点](known-issues.md) を読めば、前回の会話がなくても続けられるように書いてある。

## いつやるか

- 第2段階（10期の成長と配当）の材料の有報は年1回しか変わらない。3月決算の会社は6月下旬に提出するので、**全面更新は7月以降に年1回**。
- 株価で変わるのは第1段階（PER・PBR・配当利回り・時価総額）だけ。**月1回〜四半期に1回、判定だけやり直す**のは軽い。

## 手順

### 1. 準備

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python -c "import os; print('EDINET_API_KEY: 設定済み' if os.environ.get('EDINET_API_KEY') else 'EDINET_API_KEY: 未設定')"
```

- API キーは「設定済みかどうか」だけを確かめ、値は表示しない。
- `.cache/`（有報と株価のキャッシュ）は作業環境が変わると消える。残してあれば戻す（[費用と時間の目安](costs.md) の「キャッシュを残す」）。

### 2. 全上場会社の判定

```bash
python tools/ricky_report/run_all.py --as-of YYYY-MM-DD --out results/full
```

- キャッシュが無いと、EDINET の書類一覧（約460日分）と有報約4,300通、株価約3,800銘柄のダウンロードで約1〜1.5時間。キャッシュがあれば1〜数分（2026-10-13 にキャッシュありで計測して 75 秒）。
- 時間がかかるので Claude は Bash の `run_in_background` で実行する。止まっても同じコマンドでキャッシュの続きから進む。
- Yahoo Finance のアクセス制限（Too Many Requests）は、待って取り直すようにしてある。
- 出力: `results/full/ricky_all_YYYYMMDD.csv`（全社）、`ricky_report_YYYYMMDD.md`（機械的な表）、`series.json`（第1段階を通過した銘柄の10期の系列と注記）。`results/` はコミットしない。

### 3. 前回との差分

```bash
python tools/ricky_report/diff_passers.py results/full research/data/2026-10-13/passers.json
```

「新しく通過」「続けて通過（新しい有報の有無）」「脱落（落ちた条件）」が出る。前回の日付のフォルダは、いちばん新しい `research/data/<日付>/` を使う。

### 4. 調整漏れの洗い出し

```bash
python tools/ricky_report/scan_anomalies.py results/full
```

- BPS が前期の 0.7 倍未満・1.6 倍超に飛ぶ期、BPS 伸び率・EPS 倍率が極端な銘柄を出す。2026-10-13 はこれで MacbeePlanet の調整漏れが見つかった。
- 出た銘柄は有報の原本（純利益 ÷ EPS、純資産 ÷ BPS、発行済株式数）で、実際の増減か調整漏れかを確かめる。調整漏れならスクリプトを直し、テスト（`tests/test_screening.py`）を足して、2 からやり直す。

### 5. 新しく通過した銘柄だけ調べる

1. 入力を作る。続けて通過した銘柄は前回の調査を再利用するので `--only-new` を付ける。
   ```bash
   python tools/ricky_report/prepare_verify.py results/full <作業フォルダ> --only-new research/data/2026-10-13/passers.json
   ```
2. Workflow ツールで `tools/ricky_report/workflows/verify.js` を実行する（`args: {dir: "<作業フォルダの絶対パス>", passers: [0, 1, …], fragile: [0, 1, …]}`）。通過銘柄は「調査担当 → 反証役」の組、判定が変わりうる不通過銘柄は監査担当が、有報の原本で確かめる。
3. 結果をまとめる。
   ```bash
   python tools/ricky_report/collect_verify.py research/data/<今回>/verify.json <ワークフローの journal.jsonl>
   ```
4. 反証役の判断を読み、表記を `research/data/<今回>/labels.json` に書く（`theme`: テーマ性の表記、`doe`: DOE の表記、`evidence`: エージェントを使わず本体で確かめた銘柄の根拠）。形式は [前回の labels.json](data/2026-10-13/labels.json) と同じ。
5. 続けて通過した銘柄のうち新しい有報が出たものは、有報の「配当政策」で累進・DOE が変わっていないかだけ確かめ、変わっていれば今回の labels.json に書く。
6. 判定が変わりうる不通過銘柄で「判定が変わる可能性あり」が出たら、スクリプトの誤りとして 4 と同じように直す。

### 6. レポートを作る

- 文章のパーツ（概要・注意点・業種・分割の確認・修正点など）を作業フォルダに書く。前回の [パーツ](data/2026-10-13/parts/SUMMARY.txt) を写して、今回の事実に合わせて直すと早い。
- テンプレート（`tools/ricky_report/report_template.tmpl`）の1章の固定文（対象の社数・有報の期間・株価の日付など）を今回の値に直す。
- 組み立てる。`--verify`・`--labels` は前回 → 今回の順に並べる（後が優先）。
  ```bash
  python tools/ricky_report/assemble.py --results results/full \
    --verify research/data/2026-10-13/verify.json research/data/<今回>/verify.json \
    --labels research/data/2026-10-13/labels.json research/data/<今回>/labels.json \
    --parts <作業フォルダ>/parts --as-of YYYY-MM-DD --out research/ricky_screening_full_YYYY-MM-DD.md
  ```
- 数値は推測で埋めない（確認できなければ「未確認」）。売買の推奨はしない。

### 7. ノートを更新する

```bash
python tools/ricky_report/make_notes.py --as-of YYYY-MM-DD --results results/full \
  --verify research/data/2026-10-13/verify.json research/data/<今回>/verify.json \
  --labels research/data/2026-10-13/labels.json research/data/<今回>/labels.json \
  --report research/ricky_screening_full_YYYY-MM-DD.md
```

- 銘柄ノートの自動の部分（`<!-- auto:start -->` 〜 `<!-- auto:end -->`）だけを書き換える。「メモ」の欄は残る。今回は通過していない銘柄のノートも、今回の判定に更新される。
- `research/runs/YYYY-MM-DD.md`（実行記録）を書き、[入口](INDEX.md) の「最新の結果」を今回のレポートに書き換える。
- obsidian-notes スキルの `vault_lint.py` で、壊れたリンクや孤立したノートがないか確かめる。

### 8. コミットとプッシュ

- コミットするもの: スクリプトの修正、`research/` のレポート・ノート・`data/<今回>/`。`results/`・`.cache/`・CSV はコミットしない（.gitignore 済み）。

## Obsidian で開く

- このリポジトリを手元に clone し、Obsidian の「フォルダを保管庫として開く」でリポジトリのフォルダを選ぶ。`.obsidian/app.json`（相対パスの markdown リンク、コードのフォルダは検索から除外）が入っている。
- 最新にするには `git pull`（Obsidian Git プラグインでも可）。
- 自分のメモは銘柄ノートの「メモ」の欄に書く。コミットしてプッシュすれば、次回の Claude もそのメモを読める。

Related: [費用と時間の目安](costs.md) · [判定ルールと定義](rules.md) · [既知の問題と未確認の点](known-issues.md) · [道具の説明](../tools/ricky_report/README.md) · [入口](INDEX.md)
