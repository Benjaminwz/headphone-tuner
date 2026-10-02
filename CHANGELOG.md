# 更新紀錄

格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/)。

## [未發佈]

### 新增
- README 重新整理：版本比較表、快速開始、常見問題、建置說明
- `CONTRIBUTING.md`、Issue 範本、PR 範本
- `tools/check.py` 與 GitHub Actions：自動檢查程式能編譯、資料檔格式正確、網頁版與手機版資料一致
- 電腦版會檢查 Equalizer APO 設定檔實際有沒有套用到目前的裝置（被其他等化器程式改過、或被調兩次時提示，按「一鍵修復」）
- 電腦版偵測 Tidal 輸出到別的裝置時提示 EQ 沒套用到

- 電腦版殘響改成「兩耳都聽得到」：偏左的樂器，右耳也有殘響（跟真的房間一樣）

### 修正
- **破音**：以前只算「某個頻率最多加強多少」，但 EQ 會改變相位，滿格母帶的波峰會疊得更高；聲場寬度在左右反相時也被低估。
  用 Equalizer APO 實測一支常見耳機的校正，有 51 組「風格 × 校正」會破音（最多超出 1.2 dB）。
  現在固定預留多算 2 dB、寬度照最壞情況算，套用時再用幾種滿格測試訊號實際算出峰值，不夠就自動多降 → 實測全部不破音。
  網頁版的試聽與匯出也多留 2 dB
- **殘響有時默默不見**：Equalizer APO 不會轉殘響檔的取樣率，調音台沒開時解碼器換了取樣率，殘響就整段跳過（但音量還是降著）。
  現在常見取樣率（44.1–192 kHz）的殘響檔都會在背景先做好，由 Equalizer APO 自己依取樣率挑
- 設定檔改成「先寫暫存檔再整個換掉」：Equalizer APO 不會讀到寫一半的設定（那一瞬間會沒有降音量、爆一聲）
- 電腦版狀態列在 EQ 關閉、直通模式時不再顯示「EQ 有效」
- 電腦版同時只能開一個（重複打開會把原本的視窗叫到前面），避免兩個互相蓋掉設定
- 電腦版接管裝置時，其他程式放在調音台區塊前面的設定不再被刪掉；解除安裝時一樣能還原原本的設定

## [1.5.0] - 2026-09-28
- 支援 AirPods、USB-C EarPods：合併同款不同寫法、EarPods USB-C 同單體
- iPhone 耳機調節建議
- 網頁版（iPhone、iPad、任何瀏覽器），放在 `docs/`，用 GitHub Pages 提供

## [1.4.0] - 2026-09-28
- 手機版（Android）：同一套風格、耳機校正與暖色介面

## [1.3.0] - 2026-09-28
- 藍牙耳機適配：每個裝置各自的設定、自動跟著 Windows 輸出、音量優先、藍牙標示與提示

## [1.2.1] - 2026-09-27
- 支援 Sony MDR-XB400（用同系列 XB300／XB500 的量測推估）

## [1.2.0] - 2026-09-27
- 暖色系介面、更好上手的功能、匯出給手機

## [1.1.0] - 2026-09-27
- 安裝精靈、圖示、解除安裝自動還原

## [1.0.0] - 2026-09-27
- 繁體中文介面的耳機等化器，第一版

[未發佈]: https://github.com/Benjaminwz/headphone-tuner/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.5.0
[1.4.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.4.0
[1.3.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.3.0
[1.2.1]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.2.1
[1.2.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.2.0
[1.1.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.1.0
[1.0.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.0.0
