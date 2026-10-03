# 構造化payloadのprivacy修正（2026-10-03）

基点: `aaf193ff75055b4cf6daa64be715d126815efb38`、[PR #23](https://github.com/FYuki/digital-souls-core/pull/23)。

親レビューの合成再現で、数値を含むdict値の二重加算とフィールド間の空白除去により、
カード番号・電話番号が長い数値へ連結され、通常payloadでは検出されない問題が見つかりました。
さらにlist内の整数、重複JSONキー、encoded JSONのdecoder予算例外の検査が不足していました。

## 修正

- key/valueとarray leafを独立して正規化し、異なるフィールドを連結しない。
- 整数leafを検査し、boolean/nullとは区別する。
- nested JSONの重複キー・decoder深さ/整数変換予算・非有限値はfailedとする。
- 構造化JSONらしい不正文字列もfail-closed。通常の非JSON自然文とは区別する。
- key専用の固定markerで従来label grammarを維持し、api key/access-token等の表記揺れを検出する。
- scanner versionを`core-scanner-v2`へ更新。

## 検証

[前回証跡](2026-10-03-privacy-boundaries.md)と同じlocked環境・全コマンドを実行。
PASS: lint/format/mypy（36 files）、UT28、IT1 **384**、文書23、build・独立locked install/import。
追加60件、privacy合計 **123件**。独立レビューも **123件PASS**、残blockerなし。

actual HTTP → Conversations → PrivacyPolicyの拒否、classifier/provider未呼出し、DB/receipt不変を
合成card/phoneで確認。assistant/stream/tool args/result/schema・numeric enum・encoded JSONも検証。
別numeric fieldから偽の識別子を作らないこと、旧credential label grammarを失わないことも確認。
途中レビューでlabel表記揺れの回帰を検出し、固定marker方式と16件の回帰で修正しました。

検出の網羅性・実モデル精度は引き続き未保証。実通信・GPU・私的会話は使用していません。
ユーザーが新たに明示した保存/記憶操作仕様は、scanner修正と別の作業で反映します。
