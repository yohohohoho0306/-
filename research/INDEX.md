---
title: Ricky流スクリーニング 調査ノートの入口
date: 2026-10-13
tags: [ricky-screening, index]
---

# Ricky流スクリーニング 調査ノートの入口

Rickyさん流の増配株3段階スクリーニングを、EDINET の有価証券報告書（有報）と Yahoo Finance の株価で、上場会社全体に機械的に当てはめた調査の記録。売買の推奨ではなく、事実の整理。

Obsidian では、このリポジトリのフォルダを保管庫（vault）として開く（開き方は [次回の進め方](next-run.md) の最後）。次に作業するときは、まず [次回の進め方](next-run.md) を読む。

> [!NOTE]
> このノートと道具は、リポジトリの既定のブランチ `claude/japanese-stock-info-tool-sq2gwt` にある（2026-10-15 に作業のブランチ `claude/dividend-increase-screening-k08eyg` から統合した）。

## 最新の結果（2026-10-13）

- [全社版レポート（2026-10-13）](ricky_screening_full_2026-10-13.md): 通過61銘柄の表・印・テーマ性の根拠・第2段階で落ちた理由・業種の偏り・スクリプトの修正点。結果を見るならここ。
- [銘柄ノートの一覧](stocks/INDEX.md): 通過銘柄ごとのノート（数値・10期の推移・配当方針・テーマ性・確認で分かった注意点・判定の履歴）。銘柄を個別に見る、メモを書くならここ。
- [実行記録 2026-10-13](runs/2026-10-13.md): 何をどう実行したか、データの範囲、確認の範囲、コミット。

## 次に作業するとき

- [次回の進め方](next-run.md): 手順（判定 → 前回との差分 → 新しく通過した銘柄だけ調べる → レポート → ノート更新）。Claude にはこのノートを最初に読ませる。
- [費用と時間の目安](costs.md): 今回かかった量、次回の見込み、減らし方。
- [判定ルールと定義](rules.md): 3段階の条件、指標の定義、印、テーマ性の基準。
- [既知の問題と未確認の点](known-issues.md): スクリプトに残る弱点、確認できなかったこと。
- [道具の説明](../tools/ricky_report/README.md): tools/ricky_report のスクリプトとワークフロー。

## 過去の記録

- [手作業の調査（2026-10-12、IRBank）](ricky_screening_2026-10-12.md): 84銘柄を調べ、9銘柄が通過。2026-10-13 の試し実行で突き合わせた相手。通過9銘柄は [passers.json](data/2026-10-12/passers.json) に最小限の形で記録した（銘柄ノートの判定の履歴に出る）。

## データ（JSON。Obsidian では一覧に出ない）

- [passers.json](data/2026-10-13/passers.json): 2026-10-13 の通過銘柄の数値と表記。次回 `diff_passers.py` が「前回分」として読む。
- [verify.json](data/2026-10-13/verify.json): エージェントの調査と反証の点検の結果（出典の URL・書類番号つき）。
- [labels.json](data/2026-10-13/labels.json): 点検を踏まえて決めたテーマ性・DOE の表記と、ノートに出す補足・注意書き。
- [checked.json](data/2026-10-13/checked.json): 確かめた不通過銘柄と、洗い出し（scan_anomalies.py）で出た銘柄の結果。次回の `--skip-checked` で使う。
- `data/2026-10-13/parts/`: レポートの文章のパーツ（`assemble.py` で今のレポートを作り直せる）。

Related: [README（スクリプトの使い方）](../README.md)
