# Stage3契約整理（2026-10-03）

基点: controls epic `5bf77f3b51a6eb09d333ef65d72cf48c2fd699d7`。
PR #26のprivacy head `6a8fe58ceb32533d9e3a9a1da6c3674b01be2f11`は変更しません。

ユーザー承認されたprivate遡及削除と複数source再構成をADR 0006へ反映し、
[ADR 0007](../adr/0007-memory-provenance-and-revocation.md)に最小実装案を整理しました。
history/source/outbox契約を読み、private通知と解除後の旧memory非復活の仕組みが不足することを確認。
これは文書変更だけで、製品コード・schema・runtime・私的データは変更していません。
従来のcontrols証跡にある「ユーザー判断点」は当時の状態であり、今回の承認記録で解消しました。

実memory consumer・品質評価は未実装/未検証。Stage3実装はprivacy→controlsのmain gate完了後です。

文書ゲート: Node 24.19.0でrequired docs tests 23件、check-docs、git diff --checkがPASS。
製品コード変更がないためローカルUT/IT/buildは再実行していません。PR CIで全ゲートを確認します。

独立文書レビューでjob keyのsource epoch不足と、ContextSourceから送信境界への出典metadata不足を
指摘され、ADR 0007へ必要な拡張を明記しました。実装済みの動作とは扱いません。


## レビュー後の正確なrevisionでの再検証

2026-10-03、検証対象はcommit `35e83fd6376946b4e09ddf6412a84b2e348c076d`。
既存の記録はcommit前の作業treeでの確認を含むため、ここで確定revisionを再検証しました。
Node 24.19.0をPATHで選択し、repository rootで以下を実際に実行しました。

```sh
git rev-parse HEAD
node --version
node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
node tools/check-docs.mjs
git diff --check
```

結果: 上記SHA・v24.19.0を確認、required docs tests 23件PASS（skip/TODO/cancelなし）、
check-docs PASS、diff check成功。この再検証でUT/IT/buildは実行していません。
別のレビュー修正テスト/CIの結果と混同しません。
