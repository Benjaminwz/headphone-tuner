# Contributing

Bug 與型號請求直接開 issue。Bug 請附調音台版本、Windows／Android 版本、耳機型號與輸出裝置（藍牙、USB DAC、音效卡），以及重現步驟。

## 改程式

- 桌面版是單一檔案 `耳機調音台.pyw`，只能在 Windows 執行。用 `--config-dir <資料夾>` 測試，不會動到真正的音效設定。
- 改了風格或說明文字：執行 `python android/gen_data.py`，再把 `android/assets/data.json` 複製到 `docs/data.json`。
- 送出前執行 `python tools/check.py`。
- PR 說明改了什麼、為什麼；介面有變動請附截圖。

## 新增風格

必須有出處：研究、標準或量測，寫在程式的資料表旁邊。沒有出處的主觀調音不收。

## 文字

介面用繁體中文，專有名詞給白話說明。程式碼沿用現有命名與註解風格。
