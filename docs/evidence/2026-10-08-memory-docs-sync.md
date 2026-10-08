# Issue #105 記憶の正本文書同期の照合・検証証跡

日付: 2026-10-08

対象: [Issue #105](https://github.com/FYuki/digital-souls-core/issues/105) / [Epic #74](https://github.com/FYuki/digital-souls-core/issues/74)

起点: `origin/epic/memory-records-retrieval` / `8d95ae0729202bf5b0ef7f9efa308e14e21b120f`

文書変更commit: `36790bf30cf31226093a1550d69a3dc6934c571f`（この証跡の追加は後続commit）

作業branch: `docs/105-memory-docs-sync`

worktree: `/home/asa/.t3/worktrees/digital-souls-core/docs-105-memory-docs-sync`

実装は起点と同一。ゲートは文書変更commitと同じ実装・試験・文書の差分で実行した。
最後の説明・書式修正と本証跡追加後にはNode/check-docs/diffを再実行した。Python試験の再実行は不要と判断した。

## 変更した文書

| ファイル | 同期内容 |
| --- | --- |
| [SPEC](../../SPEC.md) | 正本保存と形成の区別、逐語撤去・削除、正本検索、日時順位、再生成未実装、実装順序 |
| [CONTEXT](../../CONTEXT.md) | Episode・Fact・Semantic、日時、Fact更新、派生index、失効の状態列 |
| [README](../../README.md) | 製品の入口を正本登録・検索へ更新し、形成未実装と実モデル未受入を明示 |
| [記憶API](../memory.md) | MemoryRecordStore / MemoryRetrieval / MemoryContext、現行のPython例、検索・送信guard、schema版6、旧消費API撤去 |
| [PostgreSQL](../postgresql.md) | open_storageのhistory/records、版1〜5から6への段階移行、旧3表のDROP・保持表・rollback |
| [履歴API](../history-api.md) | 現在版6、正本登録・検索・撤回、旧時計/Evidence説明の除去、再生成未実装 |
| [統合例](../semantic-postgresql-integration.md) | stores.recordsとMemoryRetrievalへの接続、正本候補・context、形成未実装 |
| [意味検索評価](../memory-evaluation.md) | 合成RetrievalCandidateとrank_records、文書順由来のcreated_at、PR #51の再設計との分離 |
| [privacyガイド](../privacy.md) | 撤去済み再構成consumer・抽出器の現行説明を修正し、残る分類器・検索認可を明示 |
| ADR 0007 / 0008 / 0012 / 0016 / 0017 / 0022、[索引](../adr/README.md) | 本文・Statusを維持して置換/実施注記だけを追加。索引から現行APIへ案内 |

既存の `docs/evidence/` は変更しない。`src/`・`tests/`・lockfileも変更しない。

## SPECの状態の変更前と変更後、srcの根拠

以下のファイル・行は文書変更commitでも起点と同一。
正本のschema・登録・版・撤回・検索の合成PostgreSQL試験は
[正本保存](2026-10-07-memory-record-store.md)、[検索切替](2026-10-08-record-retrieval.md)、
[逐語撤去](2026-10-08-verbatim-memory-removal.md)の証跡も照合した。
今回の文書作業ではPostgreSQL合成試験を再実行していない。

| SPECの行 | 変更前 → 変更後 | 実装済みの範囲・src根拠 / 未実装の範囲 |
| --- | --- | --- |
| §2.1 派生削除・再構成 | 実装済み → 一部 | `postgres_record_revocation.py:10` の正本・依存結果の停止/消去。再生成なし |
| §2.2 逐語保存 | 実装済み（置換対象） → 撤去済み | `postgres_schema.py:12` は版6、`postgres_db.py:206` は旧3表DROP。旧型・extractor・書込adapterは存在しない |
| §2.2 Episode | 未実装 → 一部 | `memory_records.py:287`、`postgres_memory_records.py:131` の型・登録、撤回。経験単位の照合・抽出・保存判定なし |
| §2.2 Fact | 未実装 → 一部 | `memory_records.py:307,328`、`postgres_memory_records.py:210` の独立ID・期待版更新・参照、`:482` の旧版取得。形成・発話照合なし |
| §2.2 Semantic | 未実装 → 一部 | `memory_records.py:388`、`postgres_memory_records.py:234` の両形成種別の登録・根拠検証。直接抽出・一般化の生成処理なし |
| §2.2 引用と保存文生成 | 未実装 → 一部 | `memory_records.py:87`、`postgres_memory_records.py:66` の版・epoch・話者・文字範囲検証。normalized_textはcallerが渡し、生成しない |
| §2.2 部分日時・timezone・相対日時 | 未実装 → 一部 | `memory_records.py:125,160` と `postgres_record_codec.py:101` の部分日時・timezone・精度・型付き範囲。設定・相対日時解釈なし |
| §2.2 既存逐語記憶の削除 | 未実装 → 実装済み | `postgres_db.py:206` でmemory_sources → memories → memory_jobsを移送せずDROP。版更新と同じtransaction |
| §2.3 有限batch逐語抽出 | 実装済み → 撤去済み | 旧MemoryService/LocalExtractorを撤去。現在のmemory.pyにはMemoryContextだけがある |
| §2.3 抽出・分割・冪等登録 | 未実装 → 一部 | `postgres_memory_records.py:131` のRecordBatch原子登録・冪等照合。抽出・分割なし |
| §2.3 Fact照合・更新 | 未実装 → 一部 | `postgres_memory_records.py:210` の期待版CAS・次版保存。発話からの照合・訂正判断なし |
| §2.4 部分文字列検索と意味検索 | 実装済み → 行を分割 | 部分文字列検索は撤去済み。正本の意味検索は実装済み（`memory_retrieval.py:91`、`postgres_record_retrieval.py:37`） |
| §2.4 query判定 | 実装済み → 実装済み（維持） | `memory_retrieval.py:135` のquery認可をstorage読み取りより先に実行 |
| §2.4 記憶なし継続 | 実装済み → 実装済み（未接続も明示） | `memory_retrieval.py:139` は未接続時空結果、`memory.py:62` はCoreErrorを空context化 |
| §2.4 PoC順位 | 実装済み → 実装済み（永続日時を明示） | `memory_ranking.py:108` の候補20・閾値0.54・同等帯0.002・最大5。`:135` で言及日時NULLS LAST・created_at・id |
| §2.4 last_user_mentioned_at / TOUCH | 未実装（turn保存順代用） → 一部 | `memory_records.py:266`、`postgres_memory_records.py:301` の日時保持、rank_recordsの利用。TOUCHなし |
| §2.4 context一時参照・再検証 | 実装済み → 実装済み（正本保存文を明示） | `memory.py:42` は保存文・部分日時・添付Fact・一時参照名、`:130` はdispatch guard。逐語引用・保存IDを渡さない |
| §2.5 訂正判断・旧状態 | 未実装 → 一部 | `postgres_memory_records.py:210,482` のFact旧版保持。訂正/時間変化の判断なし |
| §2.5 依存停止・再評価 | 一部（source撤回のみ） → 一部（範囲を具体化） | `postgres_record_revocation.py:10` の依存停止・本文消去、`postgres_record_retrieval.py:217` の参照版検証。再評価・再生成なし |
| §5 手順1〜3・6 | 作業順序の案 → 完了基盤と残件を明示 | 逐語削除・stated_at・操作・正本登録と検索は実装済み。timezone設定、形成、TOUCH等を後続として保持 |

期間検索・補完・有効期限/policy version互換・永続indexは未実装のまま。
型付き保存判定・形成job・Semanticの形成・一般化・consolidation等も未実装のまま。
SPECにIssue/PR番号を実装状態として追加していない。既存PoC要件書リンクは保持した。

## 追加したADR注記

- 0007: 逐語・明示抽出・再構成job・消費APIを撤去し、epoch・原子的消去・outboxと再生成できない期間の許容を維持。
- 0008: LocalExtractor / Extractionを撤去し、LocalClassifier / Assessmentの固定構造化出力を維持。
- 0012: PostgresMemory / MemoryStoreと旧factory戻り値を、PostgresMemoryRecords / MemoryRecordStore、history/recordsへ置換。
- 0016: 逐語削除をschema版6で実施済みと明示。正本保存の実装と未実装の形成を区別。
- 0017: MemoryService.extractを残すかという過去の記述を、撤去済みの実施状態と区別。
- 0022: #104の削除・書込/抽出/再構成撤去・評価最小追従の完了を明示。

0015の逐語記述は移設当時の背景で、削除決定の実施注記は0016へ集約した。
0018および0009〜0011は既存のADR0022置換注記で現在の検索・contextとの関係を説明できるため、追加なし。
追加注記を取り除いた各ADRが起点と完全一致することをスクリプトで確認した（0008の区切り改行を含む）。
Statusを変更していない。

## 指定grepの結果と残した理由

実行コマンド:

```sh
grep -rn "MemoryService\|PostgresMemory\b\|LocalExtractor\|MemoryStore\b\|stores.memory\|user_evidence\|部分文字列" README.md CONTEXT.md SPEC.md docs --include=*.md | grep -v docs/evidence/
```

出力原文は[grepのtext証跡](2026-10-08-memory-docs-sync-grep.txt)に保存した。
ファイル走査順・各行を保持し、既存証跡と本証跡は指定コマンドで除外した。

全25行。理由は次のとおり。

| 残存箇所 | 理由 |
| --- | --- |
| SPEC.md:94、docs/memory.md:59 | 部分文字列検索の撤去を明示する現行説明 |
| ADR 0008:5,15 / 0012:5,21,22 / 0017:5,138 | 旧APIを記載した歴史的本文と、その撤去を明示する今回の注記 |
| ADR 0009:5 | user_evidence原文注入の置換を明示する既存注記 |
| ADR 0010:5,15,28,29,95 / 0011:5,15,28,29,55,59 | 当時の部分文字列/MemoryService経路と既存のADR0022置換注記。本文変更は対象外 |
| ADR 0022:59,67,70,77 | 廃止する原文・部分文字列fallback・旧APIとの境界を説明する採用済み決定 |

利用文書に旧APIの実行例は残っていない。stores.memoryは残存なし。

## 中間FAILと修正

本証跡へgrep出力をそのままコードブロックで貼った状態の `node tools/check-docs.mjs` は
2回FAIL（既存ADRへの相対リンクが証跡ディレクトリ基準で検査され、missing local targetを各9件検出）だった。
1回目の修正スクリプトは抜粋位置のassertionで止まり、文書は変わらず2回目も同じFAILだった。
検証ツールはコードブロック内のinline Markdownリンクも検査する。出力原文を別text証跡へ移し、
本証跡からそのファイルを参照して修正した。最終の再実行はPASS。製品文書とUT/IT1の失敗ではない。
この中間FAILをPASSと扱わない。

## ゲート

固定toolchain: uv 0.8.22 / Node 24.19.0 / Python 3.12.3、`TMPDIR=/dev/shm`。

```sh
T=/home/asa/dev/digital-souls-evidence/history-stage1-tools
export PATH="$T/bin:$T/node/bin:$PATH" TMPDIR=/dev/shm
```

| コマンド・確認 | 結果 | 件数・補足 |
| --- | --- | --- |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS | 27。skip/TODO/cancelなし |
| `node tools/check-docs.mjs` | PASS | 全追跡text/local Markdown参照 |
| `git diff --check origin/epic/memory-records-retrieval` | PASS | whitespace |
| `uv sync --frozen` | PASS | 78 packages、lockfile変更なし |
| `uv run --no-sync pytest -m ut -q` | PASS | 473 → 473、977 deselected、1 warning |
| `uv run --no-sync pytest -m it1 -q` | PASS | 579 → 579、871 deselected、3 warnings |
| ADR本文とStatusの起点一致、src/tests/既存証跡の無変更 | PASS | 注記追加だけを除いた全文比較 |
| 更新したPython例のAST構文・Core import定義照合 | PASS | DBやモデルへの接続はしていない |
| PostgreSQL合成試験、ruff / format / mypy / build | NOT RUN | 文書のみ。監督による品質ゲート再実行は別 |
| 実DB適用・IT2 / ST・実モデル品質・remote CI・監督レビュー | NOT RUN | 対象外または引き渡し後 |

最終の指定ゲートにFAIL・SKIPはない。依存由来のStarlette非推奨alias、Pydantic ReadOnlyのwarningが残る。
deselectedはmarker選択の結果で、skipをPASS扱いしたものではない。

## 文書と実装の不一致・未解決事項

旧文書の再構成済み表示、廃止API・旧逐語context・schema版5表示、turn保存順による順位説明を修正した。
引き渡し表外のSPEC §2.1、privacyガイドでも撤去済みconsumer/抽出器を現行機能として記載していたため同期した。
形成・保存判定・保存文生成、TOUCH、再評価/再生成を保存portの実装済み範囲へ含めない。
portはprivacy分類を行わず、trusted callerが保存判定を済ませるという境界を明示した。
本作業でsrcの修正を必要とする新たな不一致は検出していない。

形成と評価再設計、利用者間共有、実モデル/実環境受入は後続であり、本Issueの合格として扱わない。
実DBへの版6適用・物理消去は検証していない。既存ADRの過去形でない本文は歴史的記録として注記で区別する。
監督が独立レビュー・必須CIを再実行しPR操作を行う。実装担当はローカルcommitだけで、push・PR作成・mergeは行わない。
