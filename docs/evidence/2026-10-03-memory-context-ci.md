# 記憶contextのCI失敗調査（2026-10-03）

## 起点と比較

base: `1f938cf3864ebaab03d98a1bbe49b76fe5803067`。
[push API CI](https://github.com/FYuki/digital-souls-core/actions/runs/37153089682)は567成功・1失敗。同一headの[PR API CI](https://github.com/FYuki/digital-souls-core/actions/runs/37153132363)は成功。失敗は`test_context_opt_in_stateless_compatibility_and_dispatch_guard`の、記憶を注入した`Inference.prepare`最終privacy認可（application.pyのprivacy_denied）。実モデルは使わないテストで、依存・workflow・コードは同一head固定。

## 決定的再現

元のテスト関数を単独で実行し、storage adapterのuuid4だけを合成UUIDへ置換した。電話番号相当の11桁が末尾に入るvalid v4 UUIDを会話IDだけに入れた場合5/5、記憶IDだけに入れた場合5/5、同じprivacy_deniedとなった。数字列を持たない対照UUIDでは5/5成功した。各試行は新しい一時DB・service・policy・FakeProviderを使い、patchも試行ごとに復元した。

scannerはUUIDのhyphenを除いた数字列を電話番号として検出する。Luhn適合数字列を持つUUIDでも同様となるため、両方を回帰テストへ固定した。Pythonのrandom seedを変える検証は不要で、生成元はuuid4のOS乱数である。実行順序や他テストのglobal state汚染がなくても再現する。最終local認可のscannerは同期処理であり、この再現に時計、async scheduler、モデル応答の揺れは必要ない。model/SDK versionも試行間で変更していない。

CIには当時生成されたUUIDが記録されていないため、その実行でどのIDが一致したかまでは特定できない。確認できたのは同じ到達点・エラーを引き起こす独立した製品不具合である。失敗CIの再実行で隠す操作はしていない。

## 修正と検証方法

保存IDを推論payloadから除きcontext内の一時参照名に置換する。scanner、user evidence、public API・保存ID・guardは維持する。テストだけの安全ID固定やskipではない。仕様は[ADR 0009](../adr/0009-memory-context-references.md)。修正後、元テストの同じ3条件×5回はすべて成功した。

新規回帰は`tests/test_memory_context_refs.py`。local/external×会話ID/記憶ID×電話/Luhnの8条件と、共有source関係1件を追加。旧frameのmemory_idを見ていた既存テストのtrigger/assertionは、新frameまたはretrieved_memory_data識別へ更新した。削除guardの拒否assertionは維持する。

主な検証コマンド: `uv run --no-sync pytest tests/test_memory_context_refs.py tests/test_memory.py -q`。必須のruff/mypy/UT/IT1/docs/build/installと、対象経路の独立プロセス反復結果・最終SHA・CIは作業PRに記録する。環境はWSL Ubuntu、Python 3.12.3、uv 0.8.22、Node 24.19.0。合成データのみでGPU・稼働runtime・私的履歴を操作しない。

## 検証結果

コード対象SHA: `9e790bfb225b0aa21fa34a77262305118ab8b4b1`。UT 30、IT1 577、文書ツール23件成功。ruff check/format、mypy 46 files、lock整合・frozen sync、sdist/wheel build、hash付き依存導入・別venv wheel isolated import成功。

元の失敗テスト1件と新規回帰9件を、ファイル順序を交互に逆転して10個の独立pytestプロセスで反復し、各10件（計100件）成功。コマンドは`pytest tests/test_memory_context_refs.py tests/test_memory.py::test_context_opt_in_stateless_compatibility_and_dispatch_guard -q`とその引数逆順。seedや全体の実行順序に依存しないUUID固定の回帰であり、確率的な成功だけを根拠にしていない。CI失敗runは再実行していない。
