# 明示的な履歴・記憶操作の検証（2026-10-03）

## 対象

- Base: scanner修正 `68b27d5046a147f8ec909f667842e1cf59cefd12`（[PR #23](https://github.com/FYuki/digital-souls-core/pull/23)）
- Code: `864ceb998f5d1e01a4ee95ec24c1e463e0c94f3b`
- 別worktree/branch: `feature/conversation-controls`
- [Issue #24](https://github.com/FYuki/digital-souls-core/issues/24)
- [ADR 0006](../adr/0006-conversation-memory-controls.md)、[履歴API](../history-api.md)

ユーザー明示の操作表を優先し、自然語で履歴保存を拒否する旧仮案を置換しました。
scanner修正と履歴操作を別commitにし、PR #23の受入れ前にmergeしません。

## 検証

[privacy証跡](2026-10-03-privacy-boundaries.md)と同じPython 3.12.3 / uv 0.8.22 /
Node 24.19.0、既存lock・全コマンドで検証しました。

PASS: lint/format、mypy **37 files**、UT **30**、IT1 **399**、文書 **23**、
sdist/wheel・独立venvへのhash固定runtime install・wheel install・隔離import。
既存Starlette/SDK/Pydanticの警告3件は残ります。実モデル・GPU・IT2/STはNOT RUNです。

以下を合成データだけで検証しました。

- 指定input indexの履歴保持、source除外、同じmetadataでのretry、変更retryの409。
- metadataをproviderへ送らず、復元時に同じsource参照とeligibilityを返す。
- thread private中の履歴保持、解除後のprivate turn非採用、進行中推論とのrevision競合。
- archiveは通常一覧だけ非表示、include_archivedで復元、sourceは有効のまま。
- 削除と内容なし通知の原子的commit/rollback、重複削除、scope分離、再起動後通知、ack。
- synthetic memory consumer fixtureで削除通知から依存レコードを除去。
  本番memory/index実装やその削除完了を示す試験ではありません。
- v1の既存履歴・receipt保持、migration途中process停止後のrollbackと再開。
- 初回schema作成の各DDL/version途中停止からの回復。
- 過去の除外/private履歴を引用する後続assistant/toolから、記憶対象へ再流入しないこと。

独立レビュー **27件PASS**（controls/history）、残blockerなし。
レビュー中に後続assistantの依存伝播不足を発見し、保守的除外と回帰で修正しました。
初回のschema回帰は新通知tableを期待値へ追加して修正、lint/typeも修正後PASSです。

## 境界

過去の発話に後付けで除外を変更するAPIはなく、completion内の指定発話を対象にします。
Stage3はsource条件とprivacy・根拠・候補型を合わせて判定する必要があります。
private切替時の既存派生memory物理削除と、複数source統合memoryの削除/再形成はユーザー判断点です。
現在はsource利用停止と永続削除通知までで、memory/index実削除は未実装です。
私的会話・secret・生ログを追加せず、稼働サービスやGPUを操作していません。
