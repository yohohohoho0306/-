export const meta = {
  name: 'ricky-verify',
  description: '通過銘柄の数値・配当方針・テーマ性を有報の原本で確かめて反証役が点検し、判定が変わりうる不通過銘柄の不合格理由を確かめる',
  whenToUse: 'prepare_verify.py で passers_N.json / fragile_N.json を作った後。args = {dir, repo, passers: [N...], fragile: [N...]}',
  phases: [
    { title: 'Passers', detail: '通過銘柄の数値・配当方針・テーマ性を確認（バッチごと）' },
    { title: 'Skeptic', detail: 'テーマ性と配当方針の主張を反証の立場で点検' },
    { title: 'Fragile', detail: '判定が変わりうる不通過銘柄の不合格理由を確認' },
  ],
}

// 2026-10-13 の実行（research/runs/2026-10-13.md）で使ったワークフローを、次回も使えるように整理したもの。
// 実行: Workflow({ scriptPath: 'tools/ricky_report/workflows/verify.js', args: { dir: '<絶対パス>', repo: '<リポジトリの絶対パス>', passers: [0, 1], fragile: [0] } })
// 初めて使うときは passers: [0], fragile: [] の1バッチで試し、結果の形を確かめてから残りを流す。
// 結果は collect_verify.py で journal.jsonl から research/data/<日付>/verify.json にまとめる。

const DIR = args.dir
const REPO = args.repo || '/home/user/-'  // リポジトリの場所（有報のキャッシュ .cache/edinet を読む）
const PASSERS = args.passers || []
const FRAGILE = args.fragile || []

const COMMON = `
## 前提（スクリプトの数値の定義）
- データは EDINET の有価証券報告書（以下「有報」）の「主要な経営指標等の推移」。EPS・BPS・1株配当は株式分割・併合を調整し、「現在の株数の基準」にそろえてある（series_10_periods）。
- ROE_yuho は有報の値（期中平均の自己資本で割る）。IRBank は期末の自己資本で割るので少し低く出るのは正常。
- PER・配当利回りは実績ベース（会社予想ではない）。時価総額 = 終値 × 期末発行済株式総数（自己株式を含む）。
- 減配 = 前期より1株配当（分割調整後）が下がった期。記念・特別配当の反動や変則決算でも機械的に1回と数えている。
- script_notes にはスクリプトが行った分割調整・変則決算・会計基準変更・連結/個別の切り替えなどが書いてある。

## 調べ方（前回わかったこと）
- 一次資料は有報の原本。PDF は https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/<書類番号>.pdf で取れる（yuho_doc_id が最新の有報）。
  ダウンロードは自分専用の新しい空フォルダに置き、テキスト化は python -I で pypdf を使う（ダウンロードしたフォルダの中でスクリプトを実行しない）。
  XBRL の要素の値は ${REPO}/.cache/edinet/reports/<書類番号>.json.gz（gzip の JSON）にもある。
- 古い期の確認には、4〜5年前の有報（script_notes に書類番号が出る）を使う。
- irbank.net・会社の IR サイトはこの環境から開けないことが多い。Web 検索はセッション全体で上限（200回）があるので、使うなら絞って使う。
- 数値は推測で埋めない。確認できない項目は「未確認」。読んだ資料（URL や書類番号とページ）を必ず記録する。
- 売買の推奨はしない。事実の整理に徹する。
`

const PASSER_SCHEMA = {
  type: 'object',
  properties: {
    stocks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          code: { type: 'string' },
          numbers: {
            type: 'object',
            properties: {
              eps_first_external: { type: ['number', 'string', 'null'], description: '9期前EPSの外部値（現在の株数基準に換算した値。換算したなら detail に書く）' },
              eps_last_external: { type: ['number', 'string', 'null'] },
              bps_all_increase_external: { type: 'string', enum: ['はい', 'いいえ', '未確認'] },
              dividend_cuts_external: { type: ['integer', 'null'] },
              verdict: { type: 'string', enum: ['一致', '不一致', '一部未確認', '未確認'] },
              detail: { type: 'string' },
              sources: { type: 'array', items: { type: 'string' } },
            },
            required: ['verdict', 'detail', 'sources'],
          },
          notes_check: { type: 'string', description: 'script_notes の分割・変則決算などが判定に影響していないかの確認結果（無ければ「注記なし」）' },
          policy: {
            type: 'object',
            properties: {
              progressive: { type: 'string', enum: ['累進配当を明記', '累進の明記なし', '未確認'] },
              doe: { type: 'string', description: '例: 「DOE 3.5%以上（中計2025〜2027年度）」「DOEの採用なし」「未確認」' },
              other: { type: 'string', description: '配当性向の目安、下限配当、総還元性向など（簡潔に）' },
              source_url: { type: 'string' },
              source_date: { type: 'string' },
            },
            required: ['progressive', 'doe', 'source_url'],
          },
          theme: {
            type: 'object',
            properties: {
              label: { type: 'string', description: '「テーマ名（根拠の要点）」の短い形。確認できなければ「未確認」、テーマと呼べる事業がなければ「該当なし」' },
              evidence: { type: 'string', description: '会社資料に書かれた、すでに売上・利益に寄与している根拠（セグメント利益、受注額など）。数値は資料にあるものだけ' },
              profit_already: { type: 'boolean' },
              source_url: { type: 'string' },
            },
            required: ['label', 'evidence', 'profit_already', 'source_url'],
          },
        },
        required: ['code', 'numbers', 'notes_check', 'policy', 'theme'],
      },
    },
  },
  required: ['stocks'],
}

const SKEPTIC_SCHEMA = {
  type: 'object',
  properties: {
    reviews: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          code: { type: 'string' },
          theme_verdict: { type: 'string', enum: ['維持', '未確認に変更', '表現を修正'] },
          revised_theme_label: { type: 'string' },
          theme_reason: { type: 'string' },
          policy_verdict: { type: 'string', enum: ['維持', '修正'] },
          revised_policy: { type: 'string', description: '修正する場合の「累進：…／DOE：…」の書き方' },
          policy_reason: { type: 'string' },
          numbers_concern: { type: 'string', description: '数値の確認結果に疑問があれば。無ければ「なし」' },
          sources: { type: 'array', items: { type: 'string' } },
        },
        required: ['code', 'theme_verdict', 'theme_reason', 'policy_verdict', 'policy_reason', 'numbers_concern'],
      },
    },
  },
  required: ['reviews'],
}

const FRAGILE_SCHEMA = {
  type: 'object',
  properties: {
    stocks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          code: { type: 'string' },
          checks: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                reason: { type: 'string', description: '確認した不合格理由（EPS 2倍未達 / BPS減少あり / 減配N回 など）' },
                script_view: { type: 'string' },
                external_view: { type: 'string' },
                genuine: { type: 'string', enum: ['本物', 'スクリプト側の誤り', '未確認'] },
                source_url: { type: 'string' },
              },
              required: ['reason', 'script_view', 'external_view', 'genuine', 'source_url'],
            },
          },
          overall: { type: 'string', enum: ['不通過で正しい', '判定が変わる可能性あり', '未確認'] },
          explanation: { type: 'string' },
        },
        required: ['code', 'checks', 'overall', 'explanation'],
      },
    },
  },
  required: ['stocks'],
}

const passerPrompt = (i) => `あなたは日本株データの調査担当です。Rickyさん流の増配株スクリーニング（3段階）で、スクリプトが「第3段階まで通過」と判定した銘柄について、次の3点を確認してください。
まず Read ツールで ${DIR}/passers_${i}.json を読むこと（銘柄ごとにスクリプトの値・10期の系列・注記・有報の配当政策の本文が入っている）。
${COMMON}
## 銘柄ごとにやること
1. 数値の確認: 9期前と直近の EPS、BPS が10期で一度も前期を下回っていないこと、10期の減配回数を、有報の原本の値と照合する。script_notes に分割・併合・変則決算・会計基準変更・個別値の使用・遡及修正などがあれば、それが判定（EPS 2倍以上・BPS 毎期増加・減配1回まで）をゆがめていないかを特に確認し、notes_check に書く。記念・特別配当が含まれる期は、有報の注記で金額を確かめて detail に書く。
2. 配当方針: 有報の「配当政策」と「経営方針」（中期経営計画の還元目標）で、累進配当の明記の有無と、DOE（株主資本配当率・純資産配当率）の採用の有無と水準（下限・目安・目標の区別、期限）を確認する。いつの資料か（source_date）も記録。
3. テーマ性: 「すでに利益化している」テーマだけを書く（例: 国土強靭化・防災インフラ、データセンター建設、半導体工場向け設備、インバウンド等）。有報の「経営成績等の状況」「セグメント情報」に、そのテーマの事業の増収・増益が実績として書かれている場合だけ label に書き、profit_already=true とする。期待・計画・業界の背景説明だけのもの、当期にそのテーマの寄与が読み取れないもの、核融合・量子・全固体電池のような「これから」の技術は加点しない（label は「未確認（理由）」または「該当なし」）。

最後に StructuredOutput で、ファイル内の全銘柄について stocks を返すこと。日本語で簡潔に。`

const skepticPrompt = (i, result) => `あなたは反証担当の監査人です。別の調査担当が、増配株スクリーニングの通過銘柄について数値・配当方針・テーマ性を調べた結果（下の JSON）を、誤りを見つけるつもりで点検してください。元データは Read ツールで ${DIR}/passers_${i}.json。
${COMMON}
## 点検の観点
- テーマ性: 主張された label が「すでに利益化している」ことを、有報の原本で本当に裏付けられるか。根拠が期待・計画・業界背景だけ、テーマと事業の関係が薄い、将来技術、当期は減収減益でテーマの寄与が読み取れない、のどれかなら「未確認に変更」。表現が誇張なら「表現を修正」（revised_theme_label は「テーマ名（根拠の要点）」の短い形）。裏付けが確かなら「維持」。
- 配当方針: 累進配当・DOE の記述が有報の配当政策・経営方針と合っているか（古い中計の値、DOE と配当性向の取り違え、DOE の下限と目標の取り違えなど）。
- 数値: numbers の記述に疑問があれば numbers_concern に書く（記念・特別配当で実績利回りが高く出ていないか、直近期に一過性の利益がないか、潜在株式による希薄化、自己株式の多さによる時価総額の差なども）。
- 推測で埋めない。裏付けが取れないものは厳しめに「未確認に変更」。

## 調査担当の結果
${JSON.stringify(result, null, 1)}

最後に StructuredOutput で、全銘柄について reviews を返すこと。日本語で簡潔に。`

const fragilePrompt = (i) => `あなたは日本株データの監査担当です。増配株スクリーニングでスクリプトが「第2段階 不通過」と判定した銘柄のうち、株式分割・併合、変則決算、会計基準の変更、報告書のつなぎ目（遡及修正）などの調整が不合格理由に関係していそうなものです。不合格理由が本物か、スクリプトの調整の誤りによるものかを有報の原本で確かめてください。
まず Read ツールで ${DIR}/fragile_${i}.json を読むこと（stage2_failures が不合格理由。series_10_periods は現在の株数基準にそろえた EPS・BPS・1株配当、script_notes は調整の内容）。
${COMMON}
## 第2段階の条件
直近10期で赤字なし・EPS が9期前の2倍以上、BPS が毎期増加（1回でも前期を下回れば不合格）、減配1回まで・無配転落なし。

## 銘柄ごとにやること
- stage2_failures の各理由について、有報の値（分割調整後の EPS・BPS・1株配当の推移）で本当にその条件を満たしていないかを確かめ、checks に書く。
- EPS 2倍未達なら、9期前と直近の EPS を確認（分割・併合の調整の基準に注意。純利益の伸びとも比べる）。BPS 減少なら該当期の前後の BPS と純資産。減配なら該当期の前後の年間配当（分割調整後）と、記念・特別配当や変則決算による見かけの減配かどうか。
- overall: すべての理由が本物なら「不通過で正しい」。どれかがスクリプトの誤りで、それを除くと通過しうるなら「判定が変わる可能性あり」。確かめきれなければ「未確認」。

最後に StructuredOutput で、ファイル内の全銘柄について stocks を返すこと。日本語で簡潔に。`

phase('Passers')
const passerRuns = pipeline(
  PASSERS,
  (i) => agent(passerPrompt(i), { label: `passers:${i}`, phase: 'Passers', schema: PASSER_SCHEMA }),
  (res, i) => res ? agent(skepticPrompt(i, res), { label: `skeptic:${i}`, phase: 'Skeptic', schema: SKEPTIC_SCHEMA })
    .then((rev) => ({ batch: i, research: res, review: rev })) : null,
)
const fragileRuns = pipeline(
  FRAGILE,
  (i) => agent(fragilePrompt(i), { label: `fragile:${i}`, phase: 'Fragile', schema: FRAGILE_SCHEMA })
    .then((res) => ({ batch: i, result: res })),
)
const [passers, fragile] = await Promise.all([passerRuns, fragileRuns])
const dropped = passers.filter((x) => !x).length + fragile.filter((x) => !x).length
if (dropped) log(`結果が返らなかったバッチ: ${dropped}（resumeFromRunId で再実行できる）`)
return { passers: passers.filter(Boolean), fragile: fragile.filter(Boolean) }
