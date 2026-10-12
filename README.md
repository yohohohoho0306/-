# jpstock 📈

日本株の**株価・値動き・投資指標・企業情報**をまとめて取得し、表 / Markdown / CSV / チャートで出力する CLI ツールです。データソースは登録不要の [Yahoo Finance](https://finance.yahoo.com/)（`yfinance` 経由）を使用します。

## 特長

- 銘柄コードを渡すだけでまとめて表示（`7203` のように数字だけでも自動で `.T` を補完）
- 複数銘柄を一度に比較
- 出力フォーマット: **リッチな表** / **Markdown レポート** / **CSV**
- **株価推移チャート**（PNG）を生成（日本語フォント自動検出）
- 取得できた項目: 現在値・前日比・出来高・PER・PBR・配当利回り・時価総額・52週レンジ・業種・事業概要 など

## インストール

```bash
# 依存ライブラリのインストール
pip install -r requirements.txt

# もしくはパッケージとしてインストール（jpstock コマンドが使えるようになる）
pip install -e .
```

## 使い方

```bash
# トヨタ・ソニー・ソフトバンクG をまとめて表で表示
python -m jpstock 7203 6758 9984

# Markdown レポートで出力
python -m jpstock 7203 --format markdown

# CSV をファイルに保存
python -m jpstock 7203 6758 --format csv -o report.csv

# 株価推移チャートを PNG で保存（期間 1 年）
python -m jpstock 7203 6758 --chart chart.png --period 1y
```

`pip install -e .` 済みなら `python -m jpstock` の代わりに `jpstock` と打てます。

### オプション

| オプション | 説明 |
| --- | --- |
| `tickers`（必須） | 銘柄コード。`7203` `6758.T` `^N225` など複数指定可 |
| `-f, --format` | `table`（既定）/ `markdown` / `csv` |
| `-o, --output` | 出力先ファイル。未指定なら標準出力 |
| `--chart PATH` | 株価推移チャートを PNG で保存 |
| `-p, --period` | ヒストリカル期間（`1mo` `6mo` `1y` `5y` など。既定 `6mo`） |
| `--version` | バージョン表示 |

### 銘柄コードの指定形式

| 入力 | 正規化後 | 備考 |
| --- | --- | --- |
| `7203` | `7203.T` | 数字だけで OK |
| `7203.T` / `7203.JP` | `7203.T` | 東証銘柄 |
| `135A` | `135A.T` | 2024 年以降の英数字コードにも対応 |
| `^N225` | `^N225` | 日経平均などの指数はそのまま |
| `AAPL` | `AAPL` | 米国株などはそのまま渡す |

## 出力例

```
                     日本株サマリー
┌───────┬──────────────┬────────┬────────┬─────────┬───────┬──────┬────────┬──────────┐
│ コード │ 銘柄名        │ 現在値  │ 前日比  │ 前日比%  │  PER  │ PBR  │ 配当…  │ 時価総額  │
├───────┼──────────────┼────────┼────────┼─────────┼───────┼──────┼────────┼──────────┤
│ 7203  │ TOYOTA MOTOR │ 2,550  │    20  │ +0.79%  │ 10.50 │ 1.20 │ 2.50%  │ 40.00 兆円│
└───────┴──────────────┴────────┴────────┴─────────┴───────┴──────┴────────┴──────────┘
```

## Ricky流 増配株スクリーニング（EDINET）

金融庁 EDINET の有価証券報告書（主要な経営指標等の推移）を使い、上場会社全体を
個人投資家 Rickyさんの 3 段階の条件に当てはめます。売買の推奨ではなく、条件への機械的な当てはめです。

```bash
export EDINET_API_KEY=...        # EDINET API v2 のキー（無料登録）。チャット等に貼らないこと
python -m jpstock.screen --codes 7203 1911   # まず数銘柄で動作確認
python -m jpstock.screen                     # 全上場会社（初回は数時間）
```

出力（`results/`）:

- `ricky_report_YYYYMMDD.md` … 第3段階まで通過した銘柄（BPS伸び率順・★☆の印付き）、第2段階で落ちた銘柄と理由、判定不能、業種分布
- `ricky_all_YYYYMMDD.csv` … 全社の指標・判定・注記（分割の検出、変則決算など）

判定の中身:

| 段階 | 条件 | 備考 |
| --- | --- | --- |
| 第1段階 | PER≦12・PBR≦1.3・ROE≧7%・ROA≧3%・配当利回り≧3%・自己資本比率≧35%・時価総額≧100億円 | **PER と配当利回りは実績ベース**（EDINET に会社予想が無いため）。金融（銀行・保険・証券・その他金融）は ROA と自己資本比率を判定しない |
| 第2段階 | 直近10期で赤字なし・EPS が9期前の2倍以上、BPS が毎期増加、減配1回まで・無配転落なし | 最新・4年前・5年前の有報をつないで10期にする。分割・併合は株式数の変化から検出して1株配当を割り戻す |
| 第3段階 | 配当政策に「累進」「DOE」の記載（DOE の数値も抽出）、PBR 0.8〜1.2倍 | テーマ性は対象外（手動で確認） |

オプション: `--prices prices.csv`（`code,price,date` の CSV で株価を渡す）、`--stage2-all`（第1段階に関係なく全社の10期データを判定）、
`--sleep`（API 呼び出し間隔）、`--cache-dir`（既定 `.cache/edinet`。書類一覧と取り出した指標をキャッシュし、再実行で続きから進む）。

必要なネットワーク接続先: `api.edinet-fsa.go.jp`、`disclosure2dl.edinet-fsa.go.jp`（コードリスト）、
株価を Yahoo Finance から取る場合は `query1.finance.yahoo.com`・`query2.finance.yahoo.com`・`fc.yahoo.com`。

注意: 分割を検出した銘柄・変則決算の銘柄は CSV の「注記」に出るので、IRBank 等で数値を確認してください。
決算期末より後の分割は Yahoo Finance の分割履歴で直近期の1株指標に反映します。

## 開発 / テスト

ロジック部分（コード正規化・指標整形・各種フォーマット）はネットワーク不要のユニットテストで検証できます。

```bash
pip install pytest
python -m pytest -q
```

## 構成

```
jpstock/
  __main__.py    # python -m jpstock のエントリ
  cli.py         # 引数解析・出力の振り分け
  fetcher.py     # yfinance ラッパ（コード正規化 → StockSummary 構築）
  formatter.py   # 表 / Markdown / CSV 整形
  chart.py       # matplotlib による株価チャート
  models.py      # StockSummary データモデル
  screen.py      # Ricky流スクリーニングの CLI（python -m jpstock.screen）
  edinet.py      # EDINET API v2 クライアント（キャッシュ付き）
  xbrl.py        # 有価証券報告書 XBRL から5期分の指標を取り出す
  history.py     # 複数の有報をつないで10期分にし、分割を調整
  ricky.py       # 第1〜第3段階の判定ロジック
  prices.py      # 株価・分割履歴の取得（yfinance / CSV）
tests/
  test_jpstock.py
  test_screening.py
```

## 注意事項

- データは Yahoo Finance に依存します。**外部ネットワークへの接続が必要**です（社内プロキシなどで Yahoo のドメインが遮断されていると取得できません）。
- 表示される株価・指標は情報提供のみを目的としており、投資判断は自己責任で行ってください。
- Yahoo Finance の仕様変更により一部の指標が取得できなくなる場合があります（その項目は `-` 表示になります）。
