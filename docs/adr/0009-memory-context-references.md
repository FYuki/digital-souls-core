# ADR 0009: モデル向け記憶contextの一時参照名

Status: Proposed

置換注記（2026-10-08）: 原文の `user_evidence` 注入と Memory/source object の記述は、[ADR 0022](0022-memory-retrieval-from-records.md) の正本・保存文 context で置換します。一時参照名は維持します。

日付: 2026-10-03

## 背景

記憶contextへ保存ID（UUID）を含めると、偶然含まれた電話番号相当・Luhn適合数字列が、送信payload全体のprivacy検査に拒否される。通常会話まで確率的に停止する。合成UUIDで既存CI失敗と同じ経路を単体再現した。

## 選択肢と決定

UUIDをscannerの検査対象から外す方式は採らない。ユーザー本文内の同じ文字列には引き続き検査が必要である。テストのIDだけ安全な値へ固定しても製品で同じ障害が残る。

推論用`retrieved_memory_data`の保存IDをcontext単位の`memory_ref`（memory-1等）と`conversation_ref`（conversation-1等）へ置き換える。同じcontext内の同じ会話には同じ参照名を割り当て、異なる会話は区別する。種別・原文・source revision/message index/epochを維持する。原文やcaller inputの書換え・符号化は行わない。

## 互換性と境界

変更はモデルへ注入する内部frameだけ。公開Memory/SourceReference、検索結果、DB保存ID、承認provenance、履歴APIは変更しない。DB migrationも不要。参照名を公開APIのIDとして利用する契約は追加しない。モデル出力から参照名を解決する機能も今回追加しない。

内部guardは従来どおり実Memory/source objectを保持し、削除・private化・policy変更をdispatch前に照合する。最終payload全体のscannerと外部送信時の分類器を維持し、UUIDの許可リストや検出閾値変更は行わない。

## 検証と制限

電話番号相当・Luhn適合の合成UUIDを会話ID/記憶IDに固定した回帰テストで、local/externalの両経路、公開ID互換、削除guardを検証する。同じ文字列がuser contentなら拒否する。複数memoryの共有source関係も確認する。

関連: [Issue #35](https://github.com/FYuki/digital-souls-core/issues/35)、[PR #37](https://github.com/FYuki/digital-souls-core/pull/37)、[原因調査証跡](../evidence/2026-10-03-memory-context-ci.md)。既存CIの失敗時UUIDはログにないため、当該実行のID自体の特定はできない。
