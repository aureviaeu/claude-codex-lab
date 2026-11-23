# 前後照片推測測試順序（#32）

`sequences.json` 列出幾段「照片依拍攝順序排列」的公開測試案例，用來量測：照片沒有可讀地名、或文字對不到單一行程站時，先標成「不確定」，再依前後照片推測（`python -m travelphotos.places.benchmark`）。

- 照片路徑是相對於 `sequences.json` 的路徑。大部分照片沿用 `../signs/` 的真實照片（來源、作者與授權見 [../signs/README.md](../signs/README.md)），排成順序只是為了測試，不代表真實的拍攝順序。
- `expected` 是 App 最後應顯示的站：文字直接讀到的站，或依前後照片「推測」的站；`null` 表示應保持「不確定」（例如前後照片分屬兩個不同景點）。
- 測試行程表與單張招牌測試相同（`benchmark.ITINERARY`）。

涵蓋的情況：

| 情況 | 照片 | 應顯示 |
| --- | --- | --- |
| 只拍到建築、沒有地名文字 | sign23.jpg（清水寺一景）夾在兩張清水寺招牌之間 | 推測：清水寺 |
| 文字不是地名（商店招牌、禁止標示） | store01.jpg、sign13.jpg 夾在兩張京都站站名標之間 | 推測：京都車站 |
| 同時寫多個地名、對不到單一站的路口指標 | multi01.jpg、sign06.jpg（鳥居題字）夾在兩張伏見稻荷站名標之間 | 推測：伏見稻荷大社 |
| 前後分屬不同景點 | held11.jpg（金閣寺建築）夾在京都車站與清水寺之間；multi01.jpg 夾在伏見稻荷與清水寺之間 | 不確定 |
| 沒有前一張 | sign70.jpg 是第一張 | 不確定 |

## 本專案產生的圖片

這兩張是本專案用 Pillow 和 Noto Sans CJK 字型畫出來的示意圖（不是照片、沒有人臉），以 [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) 提供：

| 檔案 | 內容 |
| --- | --- |
| multi01.jpg | 藍底路口指標：「← 伏見稲荷大社」與「清水寺 →」兩個地名，各附英文與距離 |
| store01.jpg | 虛構的便利商店招牌「SUNNY MART 便利商店 24H OPEN」（不是真實品牌） |

## 用自己的照片量測

把自己的照片放在 repo 最上層的 `benchmark-local/`（已列在 `.gitignore`，不會被提交；**絕對不要把自己的照片加進 repo**），再放：

- `sequence.csv`：依拍攝順序每行一張，`檔名,實際站名`（站名留空 = 應保持不確定），或格式同本資料夾的 `sequences.json`；
- 選用：`labels.csv`（單張招牌：`檔名,文字應對到的站名`）與 `itinerary.txt`（自己的行程表）。

然後執行 `python -m travelphotos.places.benchmark`，公開測試集之後會接著列出 `benchmark-local/` 的結果；也可以用 `--local 其他資料夾` 指定位置。
