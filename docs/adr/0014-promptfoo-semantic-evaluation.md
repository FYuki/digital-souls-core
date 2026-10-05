# ADR 0014: promptfooによる意味検索と出典付き回答の分離評価

Status: Proposed

日付: 2026-10-05

## 背景

[ADR 0011](0011-local-memory-embedding.md)は明示的なローカルembedding接続を、
[ADR 0013](0013-pgvector-memory-poc.md)は独立した派生indexと撤回のPoCを定めました。
固定vectorの回帰試験や検索時間の比較だけでは、同義語・言い換え・否定・無関係な質問に
対する実embedding品質、または取得した記憶に基づく回答品質を判断できません。

公開digital-soulsの合成評価分類とpromptfoo運用を参考に、Coreの検索契約に合わせた
入力・正解・評価経路を用意します。参照元は固定commit
`fce7382884d981c42be7fbd3ddaffe7469e27588` で、現在のmainと同一とは扱いません。
出典path・行・改変理由は[評価手順](../promptfoo-semantic-evaluation.md#参照元と採用理由)に記載します。

## 選択肢

既存の偽vector試験だけを品質評価として使う案、参照元の抽出器・privacy classifier評価を
一括移植する案、検索と出典付き回答に絞った独立suiteを作る案を比較しました。
最初の案では意味品質を測れず、二番目の案は別の製品policyと評価対象を混ぜるため採用しません。

## 決定

`evals/semantic/` にpromptfoo 0.117.2と専用lockfileを固定し、retrievalとanswerを
別suiteにします。通常起動や製品依存へ追加しません。
20件の独自合成ケースを、同義語、言い換え、異言語、無関係、否定、本文更新、複数source、
部分撤回、private、指定source除外、削除、Binding、長文、検索後・回答後の撤回で構成します。
公開範囲は現行の `local-private` のみで、未対応audienceは拒否を検査します。

providerは `case_id` から入力ファイルだけを読み、正解は別ファイルからassertionだけが読みます。
model promptへgold・forbidden ID・期待する事実を入れません。
source ID・revision・epoch・conversation ID・turn revision・message indexを損失なく照合し、
検索前の失効候補はembeddingにも渡しません。検索後はtokenを再確認してから回答し、
回答後も再確認して失効した回答を破棄します。

providerは独立pgvector PoC schemaを使います。実履歴の自動取込、MemoryService、
MemoryContext、本番dispatch、privacy classifierへの結線は追加しません。
このsuiteのsource変更は明示された合成projectionへの操作であり、
実thread全発話のprivate伝播を証明しません。

fixtureは4次元の固定vectorと引用付き本文連結を使います。実モデル呼出しは0回です。
local-modelは明示的なprofileと実行flagを必要とし、既存LocalEmbeddingと固定SDKの
loopback接続を再利用します。有料API、資格情報、新規モデルDLを導入しません。
未実行は `NOT_RUN` と記録し、fixtureの成功を実モデル品質へ読み替えません。

## 評価と必須ゲート

fixtureでは期待IDの順序を完全一致させ、実モデルでは関連IDのrecallと回答の限定的な
事実・引用検査を分けます。安全境界、由来、送信対象、token、削除後の不復活は必須ゲートとし、
品質点やLLM judgeで相殺しません。件数0、欠落、重複、未知case、provider error、
非有限scoreをreport gateで拒否します。promptfooの平均scoreや終了コードだけで合格にしません。

今回の回答検査は固定句と引用IDの検査です。否定句を要求して単語だけの一致を防ぎますが、
自由な言い換えや回答内の全矛盾・引用の意味的支持は判定できません。
実モデルrunでも `quality_evidence: false` を維持し、限定された合成結果を報告します。
現行の正cosine条件では無関係候補が実embeddingで返る可能性があり、空結果のgoldは
未検証の品質要件です。失敗を記録し、評価結果に合わせてgoldを黙って変更しません。

## 再現性・隔離

Node/uv/lockfileを固定し、両suiteをcacheなし・concurrency 1で実行します。
fixtureはネットワークなしの使い捨てDBと独立network namespaceを使います。
環境を清掃し、dotenv・資格情報・proxy・telemetry・共有を継承しません。
promptfoo 0.117.2のPython呼出し方式とreport形式に合わせて検査し、
最新版の文書だけから互換性を推定しません。

promptfoo 0.117.2では `--no-write` を指定した公式exportの結果配列が空になるため、
専用一時directoryのSQLiteへ合成評価だけを保存し、公式exportを厳密に再検証します。
正本履歴・本番DBへ書かず、cache・共有無効とネットワーク隔離は維持します。
raw reportとこの評価stateは合成回答などの本文を含み得るため私有directoryへ置きます。
公開証跡はcase ID・metadata・集計・固定revision・実行条件を中心とし、profileを転記しません。
source/gold/モデル設定を変えた場合は変更理由と新旧revisionを記録します。

## 影響と未検証範囲

この決定で評価ケースと実モデルの実行入口を用意できます。実embedding/chatの品質、
実GPU性能、複数回のばらつき、本番並行更新、任意のprompt injectionへの頑健性は
fixtureの成功から保証しません。既存の検索上限、保存同意、DB schema、通常起動は変更しません。
この初期sliceでは実モデルは `NOT_RUN` であり、資源と明示profileがそろった別実行で
成功・失敗を記録します。

関連Issue: [#50](https://github.com/FYuki/digital-souls-core/issues/50)。
実行方法は[評価手順](../promptfoo-semantic-evaluation.md)、
結果は[日付付き証跡](../evidence/2026-10-05-promptfoo-semantic-evaluation.md)を参照してください。
