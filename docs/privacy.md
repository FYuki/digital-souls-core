# 機微情報の検査を明示的に有効にする

この機能は単一ローカル利用者向けです。通常起動や稼働中のサービスへ自動適用しません。
既定のPrivacyPolicyは全permissionを拒否します。分類器の実モデル精度は未評価です。
私的会話の取り込み開始を意味しません。[ADR 0005](adr/0005-privacy-boundaries.md)を参照してください。

## 起動側の接続

信頼されたPython起動コードで同じpolicyをInferenceとcreate_appへ渡します。
HTTP callerはpolicy・scope・permissionを指定できません。以下は合成データ用の構成例です。

```python
from digital_souls_core.application import Inference
from digital_souls_core.api import create_app
from digital_souls_core.history import Binding
from digital_souls_core.privacy import PrivacyPolicy
from digital_souls_core.sqlite_history import SQLiteHistory

policy = PrivacyPolicy()
# characters/providerは起動側で解決した固定構成。
inference = Inference(characters, provider, privacy=policy)
policy.configure({
    Binding(inference.scope, characters[0].config.character_id):
        frozenset({"history", "local"}),
})
app = create_app(inference, history_store=SQLiteHistory(), history_policy=policy)
```

`local`として扱うのは、既存の検証済み`llamacpp_chat` loopback Profileだけです。
他のSDK経路はモデル名にlocal/Ollamaが含まれてもexternalとして扱います。
既存Profileの`external_send_allowed`は推論能力の許可として従来どおり必要です。
このフラグだけでprivacyのexternal permissionを付与することはありません。

外部送信を許す場合は、既存Providerと固定local Profileから`LocalClassifier`を作成し、
`PrivacyPolicy(classifier)`へ渡します。model digestを起動構成で固定してください。
localとexternalの両permissionが必要です。分類器は同じProvider portを利用し、transportや
外部fallbackを追加しません。proxy環境変数やcloud APIキーは既存local adapterが引き継ぎません。

## 許可の境界

| permission | 検査 | 失敗時 |
|---|---|---|
| history | 全messageの秘密値・直接識別値、userの保存拒否 | 保存・復元・receipt返却を拒否 |
| local | 実送信payloadの決定論的検査 | ローカル推論を拒否 |
| external | 決定論的検査＋ローカル意味分類 | 外部推論を拒否 |
| memory | 決定論的検査＋記憶拒否＋ローカル意味分類 | 将来の記憶形成を拒否 |

意味分類のsafe判定だけで候補の根拠・型・有用性・保存先が承認されたことにはなりません。
記憶抽出本体、repository、queue、検索は未実装です。

「覚えないで」は履歴を残しつつ記憶形成を拒否します。「保存しないで／履歴に残さないで」は
履歴保存も拒否します。現行conversation経路はturn全体が失敗し、部分inputや応答を保存しません。
この経路に「保存しないで」と入力して、同じAPIから非保存の応答だけ返す機能はありません。
非保存の会話にはstateless経路を使います。privacyを注入すればその送信前検査も有効です。
statelessの逐次応答は履歴へ保存せず、応答全体を後からマスクする機能もありません。

保存の許可と外部送信の許可は独立しています。health等の同一会話内履歴は
history permissionで扱い、external/memoryでは意味分類が機微と判定すれば拒否します。
`configure({})`で許可を撤回できます。進行中の分類は失効しますが、既に外部へ送られた内容は回収できません。
policyを差し替えた履歴serviceはfail-closedになり、削除だけはscope照合で引き続き可能です。

## 検出範囲と限界

既知credential prefix、ラベル付きpassword/key/token、PEM、Bearer、email、限定した電話形式、
Luhn整合カード番号、ラベル付き住所/ID等を対象にします。NFKC、casefold、format文字除去、
区切り文字、nested JSONとJSON内文字列を検査し、深さ・項目数・入力byteを制限します。
検出結果はフラグだけで、本文・検出値・spanを返しません。tool構造を含め全文を拒否し、部分置換しません。

任意の無印opaque値、未知vendor形式、難読化、全世界の住所/IDは網羅しません。
たとえば「password: ...」を含む一般的な設定例も保守的に拒否し得ます。
合成corpusの成功は未知の秘密や意味的機微情報を必ず検出できる証明ではありません。
LLMは誤判定し得ます。運用で検出範囲を拡張する際はscanner/prompt/policy versionと評価を更新します。
