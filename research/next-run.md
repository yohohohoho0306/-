---
title: 次回の進め方
date: 2026-10-13
tags: [ricky-screening, howto]
aliases: [続行の手順]
---

# 次回の進め方

> [!NOTE]
> このノートと道具は、リポジトリの既定のブランチ `claude/japanese-stock-info-tool-sq2gwt` にある（2026-10-15 に作業のブランチ `claude/dividend-increase-screening-k08eyg` から統合した）。新しいセッション・毎月の自動実行・clone は、そのまま既定のブランチから始めればよい。

## Claude への頼み方

新しいセッションで、次のように頼めばよい（基準日は実行する日にする）。

```text
ultracode
research/next-run.md を読んで、Ricky流スクリーニングの次回分を基準日 YYYY-MM-DD で進めて。
結果は research/ に残してコミットしてプッシュし、既定のブランチへのプルリクエストを作って。
```

- 「ultracode」（または文中の「ワークフローを使って」）は、手順5でエージェントを並べて動かす Workflow ツールを使ってよいという合図。無ければ Claude はワークフローを使えないので、手順5は Agent ツールで1バッチずつ動かすか、テーマ性・配当方針を「未確認」のままにする。
- 月1回の実行は「research/next-run.md の『月次の実行』を基準日 YYYY-MM-DD（今日）で進めて」と頼む。年1回の全面更新（7月以降）は「全面更新」と書く。

## いつやるか

- 3月決算の会社（通過銘柄の大半）は6月下旬に有報を出すので、**全面更新は7月以降に年1回**。
- 3月決算以外の会社は年中に有報を出し、株価は毎日動く。**月1回〜四半期に1回、判定だけやり直す**と、新しく通過・脱落した銘柄が分かる。新しく通過した銘柄が出たら、その銘柄だけ手順5で調べる。

## 月次の実行（月1回）

月次では、判定をやり直して前回との変化をまとめ、新しく通過した銘柄だけを調べる。続けて通過した銘柄は、新しい有報が出ていても前回の調査を使う（テーマ性・配当方針の見直しは年1回の全面更新で行う）。

1. 準備（下の手順1）。
2. 判定（手順2）。`--as-of` は今日。
3. 新しく通過した銘柄があれば、その銘柄だけを調べる（手順5）。入力は次のように作り、`fragile: []`（不通過銘柄の確認は全面更新で）で verify.js を流す。結果を `research/data/<今日>/verify.json` にまとめ、表記を `research/data/<今日>/labels.json` に書く。新しく通過した銘柄が無ければ飛ばす。
   ```bash
   python tools/ricky_report/prepare_verify.py results/full <作業フォルダ> \
     --only-new research/data/<前回>/passers.json --no-recheck-updated
   ```
4. 要約を書く。新しく通過・脱落（理由）・印の変化・新しい有報と配当政策の記載の変化・境界に近い銘柄・株価の日付・洗い出しで新しく出た銘柄・未調査の銘柄が出る。
   ```bash
   python tools/ricky_report/monthly_summary.py --as-of YYYY-MM-DD --results results/full \
     --prev research/data/<前回>/passers.json \
     --verify research/data/*/verify.json --labels research/data/*/labels.json --checked research/data/*/checked.json
   ```
   洗い出しで新しく出た銘柄があれば、手順4のとおり有報で確かめ、結果を要約に書き足す。
5. ノートを更新する（銘柄ノートの数値・判定・印が今日の株価になり、`research/data/<今日>/passers.json` が来月の「前回」になる）。
   ```bash
   python tools/ricky_report/make_notes.py --as-of YYYY-MM-DD --results results/full \
     --verify research/data/*/verify.json --labels research/data/*/labels.json \
     --report research/runs/YYYY-MM-DD.md --report-label "YYYY-MM-DD の月次の判定"
   ```
6. [入口](INDEX.md) の「最新の結果」に今月の要約へのリンクを足し、コミットしてプッシュする。頼まれていれば既定のブランチへのプルリクエストを作る（マージは利用者が行う。マージしないと翌月の実行が今月の結果を使えない）。報告は要約の「新しく通過」「脱落」「印の変化」を短く伝える。

全面更新のレポート（`ricky_screening_full_*.md`）は月次では作らない。

## 手順

### 1. 準備

```bash
pip install -r requirements.txt pytest pypdf              # pypdf は手順5でエージェントが有報の PDF を読むのに使う
python -m pytest -q
python -c "import os; print('EDINET_API_KEY: 設定済み' if os.environ.get('EDINET_API_KEY') else 'EDINET_API_KEY: 未設定')"
```

- API キーは「設定済みかどうか」だけを確かめ、値は表示しない。チャットに貼ってもらう必要もない。
- **未設定のとき**：クラウドの作業環境の設定（セッションの題名の横にある環境のメニュー → Edit）で、環境変数（または Network secrets）`EDINET_API_KEY` に EDINET API v2 のキーを入れてもらう。新しいセッションから使える。キーは EDINET の API の利用登録（無料）で取る。
- ネットワークは EDINET（`api.edinet-fsa.go.jp`・`disclosure2dl.edinet-fsa.go.jp`）と Yahoo Finance に届く必要がある（[README](../README.md) の Ricky流スクリーニングの節）。

### 2. 全上場会社の判定

```bash
python tools/ricky_report/run_all.py --as-of YYYY-MM-DD --out results/full
```

- `--as-of` は**実行する日**にする（東証の取引終了後）。株価は実行した時点の最新の終値になり、`--as-of` が決めるのは有報を探す期間（基準日の 460 日前から）と出力ファイル名だけ。実際の株価の日付は CSV の「株価日付」の列で確かめる（2026-10-13 は 95 社が前の日付だった）。
- 時間は Claude の Bash の `run_in_background` で実行する。止まっても同じコマンドでキャッシュの続きから進む。Yahoo のアクセス制限は自動で待って取り直す。
- かかる時間の目安は [費用と時間の目安](costs.md)。キャッシュ（`.cache/`）は作業環境が消えると無くなるので、新しいセッションでは基本的に取り直しになる。
- 出力: `results/full/ricky_all_YYYYMMDD.csv`（全社）、`ricky_report_YYYYMMDD.md`（機械的な表）、`series.json`（第1段階を通過した銘柄の10期の系列・注記・有報の配当政策）。`results/` はコミットしない。
- 手順3以降は `series.json` を使うので、全社の実行は `python -m jpstock.screen` ではなく `run_all.py` で行う。

### 3. 前回との差分

```bash
python tools/ricky_report/diff_passers.py results/full research/data/2026-10-13/passers.json
```

- 「新しく通過」「続けて通過（新しい有報の有無と、有報の配当政策の記載の変化）」「脱落（落ちた条件）」が出る。
- 前回分は `research/data/` のうち、`passers.json` に `latest_period_end` があるいちばん新しい日付のもの（2026-10-12 は手作業の調査で形が違うので使わない）。

### 4. 調整漏れの洗い出し

```bash
python tools/ricky_report/scan_anomalies.py results/full
```

- BPS が前期の 0.7 倍以下・1.6 倍以上に飛ぶ期、BPS 伸び率・EPS 倍率が極端な銘柄を出す。2026-10-13 は 14 銘柄が出て、確かめた結果は `research/data/2026-10-13/checked.json` の `anomalies` と [既知の問題と未確認の点](known-issues.md) にある。前回と同じ銘柄・同じ決算期なら確かめ直さなくてよい。
- 新しく出た銘柄は有報の原本（純利益 ÷ EPS、純資産 ÷ BPS、発行済株式数）で、実際の増減か調整漏れかを確かめる。調整漏れならスクリプトを直し、テスト（`tests/test_screening.py`）を足して、2 からやり直す。

### 5. 通過銘柄と、判定が変わりうる不通過銘柄を調べる

作業用のファイル（エージェントへの入力）は、セッションのスクラッチパッドなどリポジトリの外に置く。残すもの（結果・表記・文章のパーツ）は `research/data/<今回>/` に置く。

1. 入力を作る。
   ```bash
   python tools/ricky_report/prepare_verify.py results/full <作業フォルダ> \
     --only-new research/data/2026-10-13/passers.json --skip-checked research/data/*/checked.json
   ```
   - 通過銘柄は「新しく通過した銘柄」と「続けて通過して新しい有報が出た銘柄」だけが残る（新しい有報が無ければ前回の調査を使う）。年1回の全面更新では、ほぼ全銘柄に新しい有報が出ているので、通過銘柄のほぼ全部が対象になる。
   - 不通過銘柄は、調整が不合格理由に関係しうるもののうち、確認済みで決算期が同じものを除く。2026-10-13 のデータでは 40 銘柄が選ばれ、そのうち 20 銘柄は確認済み、20 銘柄は未確認（[既知の問題と未確認の点](known-issues.md)）。
2. Workflow ツールで `tools/ricky_report/workflows/verify.js` を実行する。`args: {dir: "<作業フォルダの絶対パス>", repo: "<リポジトリの絶対パス>", passers: [0, 1, …], fragile: [0, 1, …]}`。通過銘柄は「調査担当 → 反証役」の組、不通過銘柄は監査担当が、有報の原本で確かめる。
   - このスクリプトは 2026-10-13 に使ったものを、Web 検索中心から有報の原本中心に書き直したもので、この形ではまだ流していない。最初は `passers: [0], fragile: []` の1バッチで試し、結果の形を確かめてから残りを流す。
3. 結果をまとめる。journal は `~/.claude/projects/<プロジェクト>/<セッションID>/subagents/workflows/<runId>/journal.jsonl`（runId は Workflow ツールの結果に出る `wf_…`）。
   ```bash
   python tools/ricky_report/collect_verify.py research/data/<今回>/verify.json <journal.jsonl> \
     --selected <作業フォルダ>/selected.json
   ```
   `--selected` を付けると、確かめた不通過銘柄が `research/data/<今回>/checked.json` に記録される（次回 `--skip-checked` で除ける）。
4. 反証役の判断を読み、表記を `research/data/<今回>/labels.json` に書く。形式は [前回の labels.json](data/2026-10-13/labels.json) と同じ。
   - `theme`（テーマ性の表記）・`doe`（DOE の表記）
   - `evidence`（根拠の文を書き直すとき）、`theme_note`・`policy_note`（反証役と違う表記にした理由など）
   - `numbers_note`（点検の後にスクリプトを直したときの断り書き）、`caution`（判定の読み方に関わる注意。ノートの先頭に出る）
5. 「判定が変わる可能性あり」が出た不通過銘柄は、スクリプトの誤りとして手順4と同じように直す。

### 6. レポートを作る

1. テンプレートを今回のフォルダに写して直す（共通の `tools/ricky_report/report_template.tmpl` は 2026-10-13 版のまま残す）。
   ```bash
   cp tools/ricky_report/report_template.tmpl research/data/<今回>/report_template.tmpl
   ```
   - 1章の値：対象の社数（CSV の行数）、有報の期間（基準日の 460 日前〜基準日）、有報のあった社数と無かった社数（CSV の「判定」が「有報なし」の数）、株価が取れない社数（「第1段階 判定不能」の数）、株価の日付、判定の実行（`run_all.py`）。
   - 2章（試し実行と前回の手作業調査の突き合わせ）は初回だけの章。次回からは「前回との差分」（`diff_passers.py` の結果）に置き換える。
2. 文章のパーツを `research/data/<今回>/parts/<NAME>.txt` に書く。前回の [パーツ](data/2026-10-13/parts/SUMMARY.txt) を写して、今回の事実に合わせて直すと早い。印の説明（DOE の書き方の例など）は `MARKS_NOTE.txt`。
3. 組み立てる。`--verify`・`--labels` は `research/data/*/` のファイルを古い順にすべて渡す（後のものが優先。続けて通過した銘柄は前回までの調査が使われる）。
   ```bash
   python tools/ricky_report/assemble.py --results results/full \
     --verify research/data/*/verify.json --labels research/data/*/labels.json \
     --template research/data/<今回>/report_template.tmpl --parts research/data/<今回>/parts \
     --as-of YYYY-MM-DD --out research/ricky_screening_full_YYYY-MM-DD.md
   ```
- 数値は推測で埋めない（確認できなければ「未確認」）。売買の推奨はしない。

### 7. ノートを更新する

```bash
python tools/ricky_report/make_notes.py --as-of YYYY-MM-DD --results results/full \
  --verify research/data/*/verify.json --labels research/data/*/labels.json \
  --report research/ricky_screening_full_YYYY-MM-DD.md
```

- 銘柄ノートで書き換えるのは、自動の部分（`<!-- auto:start -->` 〜 `<!-- auto:end -->`）と、frontmatter のうち自動の項目だけ。手で足したプロパティ・タグ・別名、H1 の下の文、「メモ」の欄は残る。今回は通過していない銘柄のノートも、今回の判定に更新される。`stocks/INDEX.md` は毎回作り直す。
- `research/runs/YYYY-MM-DD.md`（実行記録）を書き、[入口](INDEX.md) の「最新の結果」を今回のレポートに書き換える。[費用と時間の目安](costs.md) に、`tools/ricky_report/usage.py` で数えた今回の量を足す。
- リンクの確認：obsidian-notes スキルがあれば `python <スキルのフォルダ>/scripts/vault_lint.py <リポジトリ> --exclude results` で、壊れたリンクと孤立したノートが無いかを見る。スキルが無ければ省いてよい。

### 8. コミットとプッシュ

- コミットするもの：スクリプトの修正とテスト、`research/` のレポート・ノート・`data/<今回>/`（verify.json・labels.json・checked.json・passers.json・parts・report_template.tmpl）。
- `results/`・`.cache/`・CSV はコミットしない（.gitignore 済み）。

## Obsidian で開く

- このリポジトリを手元に clone し、Obsidian の「フォルダを保管庫として開く」でリポジトリのフォルダを選ぶ。`.obsidian/app.json`（相対パスの markdown リンク、コードのフォルダは検索から除外）が入っている。
- 最新にするには `git pull`（Obsidian Git プラグインでも可）。
- 自分のメモは銘柄ノートの「メモ」の欄に、自分のタグ・プロパティは frontmatter に足してよい（次回の更新でも残る）。`stocks/INDEX.md` には書き足さない。コミットしてプッシュすれば、次回の Claude もメモを読める。

Related: [費用と時間の目安](costs.md) · [判定ルールと定義](rules.md) · [既知の問題と未確認の点](known-issues.md) · [道具の説明](../tools/ricky_report/README.md) · [入口](INDEX.md)
