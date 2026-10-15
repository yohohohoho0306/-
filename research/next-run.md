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
- 月1回の実行はルーチンが自動で始める（[月次の自動実行の設定](monthly-routine.md)）。手で始めるときは「research/next-run.md の『月次の実行』を基準日 YYYY-MM-DD（今日）で進めて」と頼む。年1回の全面更新（7月以降）は「全面更新」と書く。

## いつやるか

- 3月決算の会社（通過銘柄の大半）は6月下旬に有報を出すので、**全面更新は7月以降に年1回**。
- 3月決算以外の会社は年中に有報を出し、株価は毎日動く。**月1回〜四半期に1回、判定だけやり直す**と、新しく通過・脱落した銘柄が分かる。新しく通過した銘柄が出たら、その銘柄だけ手順5で調べる。

## 月次の実行（毎月14日。土日祝なら前の営業日）

2026-10-15 に利用者が決めたやり方。定期実行（ルーチン）は毎月10〜16日の朝 7:53（日本時間）に起動し、実行日（またはその後の取り直しの日）だけ最後まで進める。ルーチンの設定と、ルーチンに渡す文面は [月次の自動実行の設定](monthly-routine.md)。

- **実行日**：14日。14日が土日・祝日（東証の休業日）なら、その前の営業日（多くは金曜日）。`python tools/ricky_report/run_day.py` が `run YYYY-MM-DD` を出したら始め、`skip` なら何もせず終える。実行日に失敗した月は、その月の実行が終わるまで次の日以降の起動（16日まで）で取り直す（「終わった」の決め方は run_day.py の冒頭）。
- **基準日**：run_day.py が `run` の後ろに出した日付（日本時間の今日）。コンテナの `date` は UTC で、7:53 の起動では前の日になるので使わない。下の `<基準日>`・`YYYY-MM-DD` はすべてこの日付。
- **株価**：9時の取引開始より前に動くので、前の営業日の終値になる。
- **調べる範囲**：通過したすべての銘柄（新しく通過した銘柄も、続けて通過した銘柄も）。不通過銘柄は確認済みを除く。
- **作業フォルダ**：システムプロンプトにあるスクラッチパッドの下の `verify-<基準日>`（絶対パス。リポジトリの外）。
- **有報のキャッシュ**：ブランチ `claude/data-cache` に圧縮して置く（約16MB）。最初に戻し、プルリクエストの後に保存する。保存のたびに古い圧縮ファイルと、もう使わない古い書類一覧・有報を消す。

手順：

1. 実行日か確かめる。`skip` なら「今日は実行日ではない（今月の実行日は …）」とだけ報告して終える。終了コードが 0 でない（jpholiday が無いなど）なら、理由を報告して終える。
   ```bash
   pip install -r requirements.txt pytest pypdf
   python tools/ricky_report/run_day.py
   ```
2. 準備（下の「1. 準備」：テストと API キーの有無）。既定のブランチ `claude/japanese-stock-info-tool-sq2gwt` に向けた、前の月の「月次の判定」のプルリクエストがマージされずに残っていれば、番号を報告に書く（その月の結果は既定のブランチに無いので、今月の「前回」にはならない）。キャッシュを戻す。restore が終了コード 1 で終わったら（ネットワーク・認証の失敗）、キャッシュなしでは始めず、理由を報告して終える。
   ```bash
   python tools/ricky_report/cache_sync.py restore
   ```
3. 判定（下の「2. 全上場会社の判定」）。`--as-of` は基準日。キャッシュがあれば十数分（2026-10-15 の試しで11分24秒）。
4. 調整漏れの洗い出し（下の「4. 調整漏れの洗い出し」）。月次の要約（手順7）の「洗い出しで新しく出た銘柄」に出る銘柄（前回までに確かめていないもの）を有報の原本で確かめ、確かめた結果を記録する（記録すると翌月から出ない）。
   ```bash
   python tools/ricky_report/mark_checked.py research/data/<基準日>/checked.json --results results/full \
     --code <コード> --note "<何を確かめ、どうだったか>"
   ```
   調整漏れでスクリプトを直したときは、テストを足して手順3からやり直す（この月はマージしない。手順10）。
5. 調べる（下の「5. 通過銘柄と、判定が変わりうる不通過銘柄を調べる」）。
   ```bash
   python tools/ricky_report/prepare_verify.py results/full <作業フォルダ> --skip-checked research/data/*/checked.json
   ```
   - 出力の「→ N バッチ」に合わせて、Workflow ツールで `tools/ricky_report/workflows/verify.js` を `args: {dir: "<作業フォルダ>", repo: "<リポジトリの絶対パス（pwd）>", passers: [0, …, N-1], fragile: [0, …, M-1]}` で流す。
   - journal は `find ~/.claude/projects -path '*/<runId>/journal.jsonl'` で探す（runId は Workflow ツールの結果に出る `wf_…`）。まとめる：
     ```bash
     python tools/ricky_report/collect_verify.py research/data/<基準日>/verify.json <journal.jsonl> --selected <作業フォルダ>/selected.json
     ```
   - 合否の確かめ方：collect_verify の出力「research R・review V・fragile F」で、R と V が prepare_verify の passers の銘柄数と、F が fragile の銘柄数と同じなら揃っている。足りなければ、Workflow を `resumeFromRunId` で1回だけ流し直す（終わったバッチは流し直されない）。それでも足りない銘柄は、前回までの調査（無ければ「未確認」）のまま進め、銘柄名を報告に書く。R が 0 など結果の形が崩れているときは、手順6以降に進まず、結果をコミットしてプッシュし、マージせずに報告する。
6. 表記を決める（`research/data/<基準日>/labels.json`。形式は [前回の labels.json](data/2026-10-13/labels.json)。前回までの labels.json は引き継がれ、今回の分が優先される）。
   - 新しく通過した銘柄と、DOE の有無が変わった銘柄は `doe` に書く（採っていれば「DOE 3%以上（下限）」のような表記、やめたなら `"DOEの採用なし"`）。書かなければ、調査担当の結果（DOE の採用を見つけたかどうか）がそのまま使われる。
   - 反証役の判断が今の表記と違う銘柄は `theme` を書き直す。前回までの表記をやめて今回の調査の表記にするなら、値に `null` を書く。
   - 反証役が「表現を修正」とした銘柄は、修正後の表記を表にそのまま出す前に、判定ルール（テーマの事業の寄与が当期の増収・増益として有報から読み取れるか。[判定ルールと定義](rules.md)）に当たるかを決め、`theme` に書く。当たらなければ「未確認（理由）」にし、`theme_note` に理由を書く（2026-10-13 の 5284・9753 が例）。2026-10-15 の試しでは、6371 の修正後の表記が「HV需要（…HVの寄与額は不明）」で、何も書かなければ表には「HV需要」と出た。
   - 反証役の `numbers_concern` のうち判定の読み方に関わるもの（一過性の利益で EPS 2倍に届いている、記念配当で利回り3%に届いているなど）は `caution` に書く。2026-10-15 の試しでは、6371 の EPS 2.27倍は負ののれん発生益（116億円）を含み、除くと約1.38倍と指摘された。
   - 今回調べ直した銘柄では、前回までの `evidence`・`theme_note`・`policy_note`・`numbers_note`（その日の調査についての文）は自動で使われなくなる。要るなら今回の分を書く。`caution`（ノートの先頭の注意）は今回の数値で確かめ直し、当てはまらなくなったら `null` を書く。
7. 要約を書く（`research/runs/<基準日>.md`）。「前回までの表記と今回の調査が食い違う銘柄」が残っていれば、手順6に戻って決めてから書き直す。
   ```bash
   python tools/ricky_report/monthly_summary.py --as-of YYYY-MM-DD --results results/full \
     --verify research/data/*/verify.json --labels research/data/*/labels.json --checked research/data/*/checked.json
   ```
   前回（`--prev`）は省いてよい（基準日より前で、銘柄ごとの決算期が入ったいちばん新しい `research/data/*/passers.json` を自動で選ぶ。2026-11 の最初の実行では 2026-10-13）。
8. ノートを更新する（銘柄ノートの数値・判定・印が今回の株価になり、`research/data/<基準日>/passers.json` が来月の「前回」になる）。
   ```bash
   python tools/ricky_report/make_notes.py --as-of YYYY-MM-DD --results results/full \
     --verify research/data/*/verify.json --labels research/data/*/labels.json \
     --report research/runs/YYYY-MM-DD.md --report-label "YYYY-MM-DD の月次の判定"
   ```
9. [入口](INDEX.md) の「最新の結果」：見出しの日付を基準日にし、今月の要約（`runs/<基準日>.md`）へのリンクを先頭に足す（全社版レポートへのリンクは残す）。
10. コミットの直前に `python -m pytest -q` を流す。コミットしてプッシュし、既定のブランチ `claude/japanese-stock-info-tool-sq2gwt` へのプルリクエスト（題名「月次の判定 YYYY-MM-DD」）を作る。テストが通り、`git fetch origin claude/japanese-stock-info-tool-sq2gwt && git diff --name-only origin/claude/japanese-stock-info-tool-sq2gwt -- jpstock tools tests` が空（スクリプトを変えていない）なら、merge commit の方法でマージする。空でなければマージせず、何を直したかを報告する（マージしないと、翌月の実行が今月の結果を使えない）。衝突したときもマージせずに報告する。
11. キャッシュを保存する。失敗しても結果はプルリクエストに入っているので、そのまま進めて「キャッシュの保存に失敗」と報告に書く（翌月は前回のキャッシュから始まり、足りない有報を取り直す）。
    ```bash
    python tools/ricky_report/cache_sync.py save --as-of YYYY-MM-DD
    ```
12. 報告：新しく通過・脱落・印の変化・境界に近い銘柄・テーマ性や配当方針の表記を変えた銘柄を短く（要約の各節から）。マージしたか、しなかった理由。

途中で止まったとき（エラー、EDINET・Yahoo の障害、利用制限）：そこまでの結果（`research/data/<基準日>/` の verify.json・checked.json など）をコミットしてプッシュし、プルリクエストは作ってもマージしない。キャッシュは保存しない（保存すると run_day.py がその月を終わったとみなし、翌日以降の起動で取り直さなくなる）。どこで止まったか、何が残っているかを報告する。翌日以降の起動（16日まで）で、手順1から取り直す。

範囲を「新しく通過した銘柄だけ」に減らすときは、手順5の `prepare_verify.py` に `--only-new --no-recheck-updated` を足す（エージェントの使用量が大きく減る。[費用と時間の目安](costs.md)）。全面更新のレポート（`ricky_screening_full_*.md`）は月次では作らない。

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
python tools/ricky_report/diff_passers.py results/full
```

- 「新しく通過」「続けて通過（新しい有報の有無と、有報の配当政策の記載の変化）」「脱落（落ちた条件）」が出る。
- 前回分は、判定の基準日より前で `passers.json` に `latest_period_end` があるいちばん新しいものを自動で選ぶ（2026-10-12 は手作業の調査で形が違うので使わない）。別のものと比べるときは2つ目の引数にそのファイルを渡す。

### 4. 調整漏れの洗い出し

```bash
python tools/ricky_report/scan_anomalies.py results/full
```

- BPS が前期の 0.7 倍以下・1.6 倍以上に飛ぶ期、BPS 伸び率・EPS 倍率が極端な銘柄を出す。2026-10-13 は 14 銘柄が出て、確かめた結果は `research/data/2026-10-13/checked.json` の `anomalies` と [既知の問題と未確認の点](known-issues.md) にある。前回と同じ銘柄・同じ決算期なら確かめ直さなくてよい。
- 新しく出た銘柄は有報の原本（純利益 ÷ EPS、純資産 ÷ BPS、発行済株式数）で、実際の増減か調整漏れかを確かめる。調整漏れならスクリプトを直し、テスト（`tests/test_screening.py`）を足して、2 からやり直す。
- 確かめた結果は `tools/ricky_report/mark_checked.py` で `research/data/<今回>/checked.json` の `anomalies` に書く（同じ銘柄・同じ決算期は、次回から「新しく出た」に出ない）。

### 5. 通過銘柄と、判定が変わりうる不通過銘柄を調べる

作業用のファイル（エージェントへの入力）は、セッションのスクラッチパッドなどリポジトリの外に置く。残すもの（結果・表記・文章のパーツ）は `research/data/<今回>/` に置く。

1. 入力を作る。
   ```bash
   python tools/ricky_report/prepare_verify.py results/full <作業フォルダ> \
     --only-new --skip-checked research/data/*/checked.json
   ```
   - 通過銘柄は「新しく通過した銘柄」と「続けて通過して新しい有報が出た銘柄」だけが残る（新しい有報が無ければ前回の調査を使う）。`--only-new` の後に前回の passers.json を書かなければ、手順3と同じ決め方で選ぶ。`--only-new` を付けなければ、通過したすべての銘柄が残る（月次の実行）。年1回の全面更新では、ほぼ全銘柄に新しい有報が出ているので、通過銘柄のほぼ全部が対象になる。
   - 不通過銘柄は、調整が不合格理由に関係しうるもののうち、確認済みで決算期が同じものを除く。2026-10-13 のデータでは 40 銘柄が選ばれ、そのうち 20 銘柄は確認済み、20 銘柄は未確認（[既知の問題と未確認の点](known-issues.md)）。
2. Workflow ツールで `tools/ricky_report/workflows/verify.js` を実行する。`args: {dir: "<作業フォルダの絶対パス>", repo: "<リポジトリの絶対パス>", passers: [0, 1, …], fragile: [0, 1, …]}`。通過銘柄は「調査担当 → 反証役」の組、不通過銘柄は監査担当が、有報の原本で確かめる。
   - このスクリプトは 2026-10-13 に使ったものを、Web 検索中心から有報の原本中心に書き直したもの。2026-10-15 に `passers: [0], fragile: []`（6371 の1銘柄）で試し、collect_verify まで結果の形が揃うことを確かめた（不通過銘柄の監査担当はこの形ではまだ流していない。結果の数は手順の「合否の確かめ方」で確かめる）。
3. 結果をまとめる。journal は `find ~/.claude/projects -path '*/<runId>/journal.jsonl'` で探す（runId は Workflow ツールの結果に出る `wf_…`。場所は `~/.claude/projects/<プロジェクト>/<セッションID>/subagents/workflows/<runId>/journal.jsonl`）。
   ```bash
   python tools/ricky_report/collect_verify.py research/data/<今回>/verify.json <journal.jsonl> \
     --selected <作業フォルダ>/selected.json
   ```
   `--selected` を付けると、確かめた不通過銘柄が `research/data/<今回>/checked.json` に記録される（次回 `--skip-checked` で除ける）。
4. 反証役の判断を読み、表記を `research/data/<今回>/labels.json` に書く。形式は [前回の labels.json](data/2026-10-13/labels.json) と同じ。値に `null` を書くと前回までの表記を消す。
   - `theme`（テーマ性の表記）・`doe`（DOE の表記。DOE をやめた銘柄は `"DOEの採用なし"`。書かなければ調査担当の結果を使う）
   - `evidence`（根拠の文を書き直すとき）、`theme_note`・`policy_note`（反証役と違う表記にした理由など）
   - `numbers_note`（点検の後にスクリプトを直したときの断り書き）、`caution`（判定の読み方に関わる注意。ノートの先頭に、書いた日と一緒に出る）
   - `evidence`・`theme_note`・`policy_note`・`numbers_note` は、その日の調査についての文なので、後の日に調べ直した銘柄では使われなくなる。
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
