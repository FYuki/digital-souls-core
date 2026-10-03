# float数値境界の修正（2026-10-03）

基点: `68b27d5046a147f8ec909f667842e1cf59cefd12`、[PR #23](https://github.com/FYuki/digital-souls-core/pull/23)。
親レビューで、tool enumの合成カード番号をfloatにするとscannerがleafを無視し、
classifier/providerへ到達し得る問題が見つかりました。

## 修正と制約

- binary floatの絶対値1e13以上は元の桁の精度を保証できないためfailedとして拒否。
- 小さな有限floatはdecimal固定表記で検査。非有限値も拒否。
- JSON文字列のparse_floatはDecimal。decimal・指数表記の数字を丸めず展開して検査。
- decoded scalar数値も検査し、過大/過小指数は展開前に予算で拒否。
- scanner versionはcore-scanner-v3。普通のfloat、boolean/nullは秘密と誤認しない境界を検証。

## 検証

前回と同じlocked環境・必須コマンドでPASS: lint/format/mypy（36 files）、UT28、IT1 **440**、
文書23、sdist/wheel build・独立locked install/import。数値回帰は**116件**（今回56件追加）。
合成decimal/exponent/integral float/精度超過/NaN/Infinity/通常floatを検証。
tool enumとencoded inputがclassifier/providerへ到達せず、履歴が不変であることを検証。
私的データ・実推論・GPU・サービス操作は使用していません。
Stage3の遡及private・複数出典削除ポリシーは未決定のままです。


独立レビューの途中で小さい指数/ゼロの桁合わせをカードと誤認する問題を検出し、
数値の整数部・有効小数部を独立検査する修正と6件の回帰を追加しました。
decoded JSONは元字句を重複検査せず、leafを検査します。privacy回帰合計179件PASS。

JSONの`1e309`もDecimalで無限大へ丸めず読み取りますが、許容指数の上限308を超えるため
failedとする回帰を追加しました。負側も同様に拒否します。
