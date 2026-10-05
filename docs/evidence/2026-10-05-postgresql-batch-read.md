# PostgreSQL 一括読取のレビュー対応（2026-10-05）

対象: [統合 PR #46](https://github.com/FYuki/digital-souls-core/pull/46)、
[CodeRabbit 実レビュー](https://github.com/FYuki/digital-souls-core/pull/46#pullrequestreview-5409105786)、
[N+1 読取の指摘](https://github.com/FYuki/digital-souls-core/pull/46#discussion_r4180052524)。

## 対象 revision と修正

CodeRabbit は `75192e68b5a47a629dd8d4535cb371d1802dadcc` の46変更ファイルを実レビューし、
Trivial / Performance & Scalability の指摘を1件出した。概要だけの通知や draft skip ではない。
現在 head の差分レビューを一度だけ手動依頼した。追加のレビュー依頼は送らない。

修正 revision: `7bdee7975458513b1fd5ba741efcbd03e099ff31`。
`_memories` は memory_sources と必要な turn を一括取得し、`valid` / `_current` も同じ取得処理を使う。
conversation / revision はペアで join し、無関係な組の本文は取らない。
単体取得と同じ row→Evidence 判定を共有し、private、指定発話除外、role、本文、epoch を照合する。
candidate順・source順、Binding分離、同じtransactionでの排他、1000件上限、空集合の意味を保つ。
schema・保存経路・公開契約は変更しない。

## 検証結果

WSL Ubuntu、Python 3.12.3、uv 0.8.22、固定 PostgreSQL 18.6 の隔離合成 DB。
実モデル・実履歴・実 credential・稼働 DB を使わない。

| 検証 | 結果 |
| --- | --- |
| PostgreSQL 契約 | PASS、83件 = 統合済み67 + 新規16 |
| UT / IT1 | PASS、216 / 746件 |
| ruff / format / mypy | PASS、66 files |
| build | PASS、sdist / wheel |
| 独立レビュー | PASS、未解決P0/P1/P2なし |
| 実モデル品質・実配備 | NOT RUN |

`bash tools/test-postgres.sh` の合成実 DB 試験で `psycopg.Connection.execute` を観測した。
明示的な接続設定・lockを含む呼出し回数は次のとおり。libpq内部のBEGIN/COMMIT等を含む
全wire packet数や、実行時間のベンチマークではない。

| 操作 | 記憶1 / 10 / 20件 | 出典1 / 8 / 16件 |
| --- | --- | --- |
| candidates / results / search | 6 / 6 / 6 | 6 / 6 / 6 |
| valid | 5 / 5 / 5 | 5 / 5 / 5 |

データ参照SELECTは候補取得3、有効性確認2に対応する。libpqの実受信結果を消費せず観測し、
指定したペアの本文だけを取得することも確認した。実効性を失ったsourceを持つactive記憶、
private・除外・epoch・削除、複数turn/position、空集合、順序の回帰も検証した。

修正に対する独立レビューはCodeRabbitの再レビューの代用としない。CodeRabbitの対象commitと
修正commitを区別して記録し、最終headのCIと対応コメントをPRに追記する。
main と dogfood は変更しない。WSL起動時に既存設定の重複/未知key警告が出たが、
コマンドと試験は成功しており、今回の作業からWSL設定は変更していない。
