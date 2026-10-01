# 貢獻指南

歡迎回報問題、提出想法、補耳機型號或改程式。

## 回報問題／提議
到 [Issues](../../issues/new/choose) 選對應的範本。回報 bug 請附：Windows／Android 版本、調音台版本、耳機型號、重現步驟。

## 改程式
1. Fork 後從 `main` 開新分支。
2. 電腦版是單一檔案 `耳機調音台.pyw`（Python + tkinter，只在 Windows 上執行）。
   用 `--config-dir <資料夾>` 測試，不會動到真正的音效設定。
3. 改了風格或名詞說明：執行 `python android/gen_data.py`，並把 `android/assets/data.json` 複製為 `docs/data.json`。
4. 送出前執行 `python tools/check.py`，需要通過。
5. 開 Pull Request，說明改了什麼、為什麼；介面有變動請附截圖。

## 新增風格
風格要有依據（研究、標準或量測），並把依據寫在程式裡，這是這個專案的原則：不靠感覺調聲音。

## 風格約定
- 介面文字用繁體中文，用白話說明專有名詞。
- 保持與現有程式碼一致的命名與註解風格。
