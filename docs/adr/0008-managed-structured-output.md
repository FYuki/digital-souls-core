# ADR 0008: 管理された分類器・抽出器の構造化出力

Status: Proposed
日付: 2026-10-03

## 背景と選択肢

ローカルGemmaの合成データsmokeでは、分類器と抽出器がJSONコードブロックを返し、既存のstrict parserで拒否された。安全側の拒否は維持するが、正常な記憶処理が進まない。promptだけの指定、コードブロック除去、providerのJSON Schema制約を比較し、最後を選ぶ。

## 決定

管理されたLocalClassifierとLocalExtractorだけに、固定の`response_format.type=json_schema`と`json_schema.schema`を送る。schemaは既存のAssessment/Extractionから生成し、`strict=true`を指定する。呼び出し側の任意kwargsや公開APIには開放しない。通常の会話生成経路は変更しない。

対応契約は`llamacpp-b11347-json-schema-v1`。固定revisionの[公式parser](https://github.com/ggml-org/llama.cpp/blob/5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd/tools/server/server-common.cpp)がこの入れ子形式を受け取り、JSON Schemaを生成制約へ渡す。[server仕様](https://github.com/ggml-org/llama.cpp/blob/5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd/tools/server/README.md)も参照する。

ローカルのstrict parser、機微判定、出典・候補整合検証は引き続き必須。未対応HTTPエラー、不正JSON、コードブロック、schema違反はfail-closedとし、制約なしの再試行は行わない。構造化出力は分類精度や意味の正しさを保証しない。

## 承認の互換性

既存のmodel/profile/loopback destination provenanceに、対応契約version、送信schema wrapper全体のSHA-256、LiteLLM/OpenAI SDK versionを追加する。契約・schema・SDKの変更や旧形式の承認は一致しないため、既存のstale/再承認境界でモデル送信前に拒否する。既存承認の自動更新、DB migration、本文の自動再送は行わない。

契約versionは実装が対応する能力の宣言であり、稼働serverの署名検証ではない。運用者は既存のdestination_versionとモデル識別子を実際の配置に合わせて管理する。schemaを無視するserverの検出を一般保証するものでもなく、返却値は必ずローカル検証する。

## 影響と証跡

依存追加なし。新規公開設定なし。旧承認で保留されたjobは明示的な再承認・再実行が必要になる。実機検証の範囲と制限は[検証証跡](../evidence/2026-10-03-structured-memory.md)を参照。関連: [Issue #35](https://github.com/FYuki/digital-souls-core/issues/35)。PRはIssueから追跡する。
