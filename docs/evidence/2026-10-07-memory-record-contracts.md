# 記憶正本のdomain契約の実装・検証記録

検証日: 2026-10-07（UTC）。対象: [Issue #71](https://github.com/FYuki/digital-souls-core/issues/71)。
起点: `4d1c9b5e33bf014f3af759404be370fa5142d97d`（`epic/memory-canonical-records`）。
作業branch: `feature/71-memory-record-contracts`、worktree: `feature-71`。
監督レビュー修正の起点: `2102c3e02279bc0b230fc9e44da2fe5a0e1f98d1`。
この証跡を含む追加commitの製品コード・UTが検証対象です。

## 正本と範囲

AGENTS / CONTRIBUTING、Issue #71・[#72](https://github.com/FYuki/digital-souls-core/issues/72)、
[ADR 0016](../adr/0016-memory-kinds-and-records.md)、
[ADR 0017](../adr/0017-memory-formation-admission.md) §4・§6、
[ADR 0019](../adr/0019-memory-correction-invalidation.md) §1・§4・§5、
[SPEC](../../SPEC.md) §2.2・§3.1を確認しました。
監督が本依頼で指定した引用・5W・日時・独立性等の解釈に従っています。
過去の開発記録は今回の操作許可とせず、今回の範囲指定を優先しました。

変更ファイルは、新規domain module、新規UT、本証跡、`docs/memory.md` の説明です。
既存 `memory_contracts.py`、既存テスト、SPECの状態は変更していません。
保存・schema・adapter・抽出・検索・日時解釈・Reflectionは実装していません。
push・PR作成・mergeは実行していません。

## 型と不変条件

| 型・関数 | 契約 |
| --- | --- |
| `Citation` / `Speaker` | Binding、個別のSourceVersion、明示話者、message内の半開文字範囲。0≦start<end、epoch≧0、turn revision≧1、message index≧0 |
| `FiveW` / `ExplicitReason` | 非空の述語を必須とし、対象・Who・When・Where・Whyは未知を保持。明示理由には引用1件以上を必須とし、記録と同じBindingを検証 |
| `PartialDateTime` / `TimePrecision` | 年・月・日・時・分・秒精度。精度に必要な成分のみ保持し、欠落・過剰成分・不正暦・bool等の非整数を拒否 |
| `TemporalValue` | 不明、部分日時の点、開始≦終了の範囲、解釈時のタイムゾーン文字列。日時を補完せず、範囲の端点は同じ精度を要求 |
| `Episode` / `EpisodeContext` | 経験の5W・経験日時・不明可のtz-aware experienced_at・ACTUAL/HYPOTHETICAL/FICTION・引用1件以上 |
| `Fact` | 呼出し側が採番する安定fact_idの内容一版。版ごとに5W・対象日時・保存文・引用1件以上を保持し、IDを内容から導出しない |
| `EpisodeFactLink` | link_id・整数版≧1・Binding・tz-aware created_at・RecordState・Episode/FactのRecordRefだけを持つ本文なしの参照。参照の種別とBindingを照合し、保存文・last_user_mentioned_atを持たない |
| `Proposition` / `FormationType` / `Semantic` | 非空の主体・属性・値、適用時期、形成種別。DIRECT_EXTRACTIONはuser引用1件以上を必須とする |
| `EpisodeEvidence` | 同じBindingのEpisodeへの参照と、その引用元SourceReferenceの非空・不変集合 |
| EXPERIENCE_DERIVEDの独立性 | 同一Episode IDの出典集合を合算し、異なるIDで互いに素な出典集合を持つ2件以上を必須とする。epoch・版・範囲の差や重複IDで独立性を増やさない |
| `RecordRef` / `RecordKind` | 種別・安定ID・整数版≧1・Bindingを持つ参照 |
| `RecordHead` / `dependency_invalidated` | 本文なしの現在参照・状態、または現在記録と照合する純粋関数。不存在・版不一致・利用停止・種別/ID/Binding不一致を失効と判定 |
| 全記録 / `RecordState` | 安定ID・整数版≧1・Binding・tz-aware created_at・ACTIVE/SUSPENDED。frozen値型、不正値は生成時にValueErrorで拒否 |
| `Episode` / `Fact` / `Semantic` の本文 | さらに非空保存文・不明可のtz-aware last_user_mentioned_atを保持。引用はtuple、出典集合はfrozenset |
| repr | 保存文、5Wの発言内容、理由、命題内容を出さない。引用は本文をコピーしない |

`_RecordFields` はEpisode・Fact・Semanticの共通フィールドの内部再利用で、汎用の記憶型として提供しません。
構造の検証は保存許可や出典の真実性を意味しません。引用範囲・話者と履歴の対応、sourceの現在版・
適格性、Episode出典集合と参照先の対応、撤回・旧版保持は後続の保存portで検証します。

## TDDの想定FAIL

最初に `tests/test_memory_records.py` を作成し、domain moduleの作成前に以下を実行しました。
この時点のテストファイルSHA-256は
`bb0bda05d4f73e422fccc35d8a112189d5c0ab1bcf752665cefb6bb7d1fd0b9b` です。

```sh
uv run --no-sync pytest -m ut -q tests/test_memory_records.py
```

結果: **FAIL（想定どおり）**。終了code 1、収集エラー1件、0.22秒。

```text
E   ModuleNotFoundError: No module named 'digital_souls_core.memory_records'
ERROR tests/test_memory_records.py
1 error in 0.22s
```

実装後は新規UT 202件がPASSしました。次に本文消去後の失効判定用 `RecordHead` のテストを
先に追加して再実行し、未実装の `RecordHead` のImportError（収集エラー1件、終了code 1、
0.14秒）を確認しました。追加実装後の新規UTは **PASS: 206件**（0.18秒）です。
skip・xfail・dummy testはありません。

## 監督レビュー修正のTDD

EpisodeFactLinkのfixtureから保存文・最終言及日時を除き、フィールドが指定の7個だけであること、
本文用フィールドを受け付けないこと、両参照の種別・Binding不一致や欠落を拒否することを先にテストしました。
修正前のテストファイルSHA-256（format前）:
`d192b4b2fb6455b61c8da924f63e545e934107bd522bd2059b664299bb461726`。

```sh
uv run --no-sync pytest -m ut -q tests/test_memory_records.py -k 'episode_fact_link_has_only_content_free_reference_fields or link_rejects_wrong_kind_or_binding'
```

結果: **FAIL（想定どおり）: 7 failed、201 deselected、終了code 1、0.16秒**。
旧実装は次のTypeErrorで、保存文・最終言及日時なしの生成を拒否しました。

```text
TypeError: EpisodeFactLink.__init__() missing 2 required keyword-only arguments: 'normalized_text' and 'last_user_mentioned_at'
```

実装後の契約UTは **PASS: 208 passed、0.18秒**。
本文用の不変条件とrepr検証はEpisode・Fact・Semanticだけに適用し、全記録共通の
版・Binding・登録日時・状態・不変性、およびEpisodeFactLinkの依存失効判定は維持しています。

## 固定toolchainと最終品質ゲート（監督レビュー修正後）

固定toolchain（uv 0.8.22、Node 24.19.0）のディレクトリをPATHの先頭に置き、
`TMPDIR=/dev/shm` を設定して再実行しました。

確認値: uv 0.8.22、Node v24.19.0、CPython 3.12.3。
最終のdomain module / UTのSHA-256:

```text
ec8ec2cfa3489fe79b58f5055c81dee429b126baa772105b93a467ef6e8406f6  src/digital_souls_core/memory_records.py
44eca49c07495d51024563cfb0dab0680cee7f2f7aa32c3985b0fd09347ecc3c  tests/test_memory_records.py
```

| コマンド | 結果・件数 |
| --- | --- |
| `uv sync --frozen` | PASS: 78 packages audited、lock変更なし |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS: 指摘0件 |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS: 81 files |
| `uv run --no-sync mypy` | PASS: 81 source files、指摘0件 |
| `uv run --no-sync pytest -m ut -q` | PASS: 477 passed、1041 deselected、skip/xfail 0、3.11秒 |
| `uv run --no-sync pytest -m it1 -q` | PASS: 863 passed、655 deselected、skip/xfail 0、18.75秒 |
| `uv build --no-build-isolation` | PASS: sdist・wheelの2成果物 |
| `bash tools/test-postgres.sh` | PASS: 178 passed、1340 deselected、skip/xfail 0、19.11秒 |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS: 必須23件、skip/todo/cancel 0 |
| `node tools/check-docs.mjs` | PASS: 1実行、追跡テキスト・Markdown参照の指摘0件 |
| `git diff --check` | PASS: 指摘0件（stage後も確認） |

PostgreSQLはdigest固定の使い捨て合成コンテナを `--network none`・公開portなしで使用しました。
Starlette/AnyIOのDeprecationWarningとPydantic TypedDict ReadOnly警告は既存依存由来で、
UTでは1件、IT1では3件、PostgreSQLでは1件です。FAIL・SKIPに変換された結果はありません。
IT2 / ST（実モデル・実環境）は **NOT RUN**、今回の対象外です。

## 初回実装時のFAILと再実行（修正起点commitの記録）

全品質ゲート初回のUTは **FAIL: 22 failed / 449 passed**、IT1は
**FAIL: 82 failed / 781 passed** でした。SQLiteの既存保存先ガード
`history must be outside Git and symbolic links` による失敗です。
`/tmp/.git` は事前・失敗後の確認では存在せず、ガードが拒否した時点の環境の原因は未確定です。
今回のdomain moduleは既存storeから参照されていません。
保存先の保護を変更せず、指定の `TMPDIR=/dev/shm` で両suiteを再実行すると全件PASSしました。
その後のRecordHead追加を含む最終コードでも同じ設定で全ゲートを確認しています。

開発途中のlintはFAIL（長行3件・setattrの指摘1件）、mypyはFAIL（合成AccessScopeの
Literal不一致1件）でした。新規テストだけをformat・修正し、最終検査はPASSです。

監督レビュー修正の品質ゲート初回ではmypyが **FAIL: 6 errors in 1 file（81 source files）**。
本文用フィールドの拒否テストで動的な不正引数を渡す辞書を `dict[str, Any]` と明記し、
最終mypyは **PASS: 81 source files、指摘0件**。修正後にruff check・formatと全UTも再実行しました。
IT1・PostgreSQL・buildはこのテストの型注釈修正前に実行済みで、製品コードは同じです。

## 判断・監督への引継ぎ

- Factは履歴配列を抱えず、安定IDの内容一版として表現しました。旧版保持・楽観排他は#72の責務です。
- 異なる精度の日時範囲は、欠損成分を補わず順序を確定できないためfail-closedで拒否します。
- RecordHeadは、#72の本文消去後も依存先の状態を判定できるための本文なしの値です。
- EpisodeFactLinkの本文・最終言及日時を除き、#72に参照用の不要な本文保存・消去を要求しない契約に修正しました。
- 必須ゲートをPASSとして報告する際も、初回FAILと環境を変えた再実行を区別してください。
- 日本語・簡潔な報告は今回の明示指示です。新しい回答の好みの推測はありません。
- 編集先を指定worktreeに限定したため、共有private-knowledgeには書き込まず、本証跡を記録担当へ返します。
  共有要約の更新、push・PR作成・mergeは監督の担当です。
