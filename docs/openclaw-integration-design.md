# OpenClawとの連携検討

2026-10-10時点の調査・提案。常駐Coreの方針は[ADR 0025](adr/0025-shared-runtime-interfaces.md)で採用済み。
以下の専用連携方式・入力契約・受入条件案は未採用・未実装である。
関連: [Epic #134](https://github.com/FYuki/digital-souls-core/issues/134)。

## 結論

CoreにOpenClaw専用のHTTP APIを直ちに追加する必要性は確認できない。
基本的な接続はOpenAI互換Chat APIを使い、本文形式などの互換対応は汎用の入力境界で行う。
ただし、実ユーザー発話とOpenClawの内部文脈の区別には、由来を保持する連携が必要になる。
専用URLを設けるだけでは失われた由来を復元できない。

推奨案は、OpenClaw側に薄い連携プラグインを置き、Core側には他の外部Agentでも使える
明示的な入力由来の契約を設けること。プラグインの拡張点と契約の形式は実測後に決める。
専用Core runtime、文字列の接頭辞で内部文脈を見分ける処理は推奨しない。

## 確認できたことと制約

Coreの`Inference.prepare`は、末尾から最初に見つかった`role=user`の本文を、
Lore照合とcontext取得に渡す。記憶検索は明示的な会話経路だけだが、Lore照合はstatelessでも行う。
したがって「stateless接続なら内部文脈の混入は影響しない」という説明は正しくない。

事前のOpenClaw 2026.9.9合成要求調査では、内部実行文脈が最後のuserメッセージになる例が
報告されている。今回はCoreの該当コード、同版の配布ドキュメント、公式資料を照合した。
要求捕捉・実モデル接続の再実行はしていない。この観測を全runtime・全設定へ一般化しない。

OpenClawの公式資料には以下の拡張点がある。

- [Custom providers](https://docs.openclaw.ai/gateway/config-tools/custom-providers):
  `baseUrl`、API種別、互換設定などで接続先を構成できる。接続設定だけでは発話の由来は補えない。
- [Prompt/session hooks](https://docs.openclaw.ai/plugins/hooks/prompt-and-session):
  `before_prompt_build`の`inputProvenance`は外部入力・内部入力等の区別を持つが、省略可能。
  欠落を人間由来と判定できず、turn単位の由来だけで送信messages全要素の由来が分かるとは限らない。
- [Context engines](https://docs.openclaw.ai/plugins/architecture-internals/context-engines):
  文脈の取り込み・組み立て・圧縮を扱う拡張である。今回の入力識別だけのために置換するには責務が広い。

これらの存在は、必要な情報を最終HTTP要求まで運べることの実証ではない。
通常のChat形式のrole/contentだけから、人間の入力と内部文脈を常に判別することはできない。

## 責務の案

| 項目 | Core | OpenClaw連携側 |
| --- | --- | --- |
| 人格・Lore | 正本と適用判断を所有 | 人格を別に複製せず、実行環境の指示を提供 |
| 推論 | 共通runtimeからproviderへ送信 | Coreを呼び、tool実行を継続 |
| 入力の由来 | 明示的な契約を検証 | 実発話・内部文脈・tool結果・要約の由来を保持 |
| 履歴と記憶 | 保存同意、正本、検索、撤回、Bindingを管理 | セッションとturnの対応、再送・中断を伝達 |
| 文脈圧縮 | 記憶の正本と出典を保つ | LLM用の作業文脈を圧縮。要約を人間の原発言として登録しない |

同じ人格でも、別clientの記憶へアクセスするには別途共有契約が必要である。
OpenClawのsession IDや任意ヘッダーをCoreの信頼済みsubject/client/audienceに直結させない。
入力由来とアクセス権限は別の情報として扱う。

会話保存は、モデル要求ごとに全履歴を追記する方式を避ける案とする。tool往復や再送で重複するため、
元のturn・request・版を対応付ける必要がある。OpenClaw側の保存・削除とCore側の保存・削除は
独立しているので、一方の削除で両方が消えるとは扱わない。

## 選択肢と再検討条件

1. 互換APIと設定のみ: 基本の回答生成・tool往復の接続に使う。Loreの実発話照合や記憶連携の解決とは区別する。
2. OpenClaw用プラグインとCore共通契約: 推奨候補。由来・セッション・turnを明示する。
3. CoreのOpenClaw専用API: 2では表現できないライフサイクル上の差が実証された場合に再検討する。
   採用しても同じruntimeを呼ぶ薄いadapterに限定する。
4. Context engine置換: 圧縮や履歴組み立てそのものをCore連携へ委ねる要求が生じた場合に検討する。

## 次の検証と受入条件案

- OpenClawの固定版で、元入力から最終要求までのどの段階で由来が失われるかを合成データで確認する。
  pluginで動的情報を伝えられる拡張点、並行セッション・tool継続時の対応関係を確認する。
- 人間発話あり／内部文脈のみ／heartbeat／tool継続／圧縮後／再送・中断を分ける。
  現在の人間発話がない場合や由来不明時のLore・検索・形成の挙動を、実装前に合意する。
- 本文中に内部文脈と同じ接頭辞が現れても誤分類しない。由来欠落を人間由来へ自動昇格しない。
- 並行セッションの混線、二重保存、private・削除後の再送による復活、Binding越境を拒否する。
- 新しい入口を追加しても通常のChat APIと既存の保存opt-inを変更しない。

今回の実接続・IT2・STはNOT RUN。プラグイン実装や実環境設定の変更はこの文書の対象外。
