# 更新紀錄

格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/)。

## [未發佈]

## [1.7.0] - 2026-10-25

### 新增
- 電腦版殘響改用聲學模擬的真實房間：鏡像聲源的早期反射（3–5 階、會檢查有沒有被擋住）＋顯示卡聲線追蹤的後段（每個聲源 3,355 萬條）＋頭部模型；錄音室照 ITU-R BS.1116 聆聽室、音樂廳照維也納金色大廳（含陽台、舞台）。各頻段殘響時間對上原本的數據，波峰比舊版低約 1–2 dB → 防破音少降一點音量。產生程式 `tools/殘響模擬.py`、量測結果 `殘響/結果.json`
- 交叉饋送改用頭部模型：模擬前方 ±30° 兩顆喇叭繞過頭到另一耳的聲音（有時間差、高頻被頭擋掉），人聲這類在中間的聲音音色完全不變
- 輸出解析度選 88.2 kHz 以上時，電腦做重建濾波（線性相位、阻隔 140 dB），EQ 高頻更準；建議 32-bit／352.8 kHz

## [1.6.0] - 2026-10-25

### 新增
- README 重新整理：版本比較表、快速開始、常見問題、建置說明
- `CONTRIBUTING.md`、Issue 範本、PR 範本
- `tools/check.py` 與 GitHub Actions：自動檢查程式能編譯、資料檔格式正確、網頁版與手機版資料一致
- 電腦版會檢查 Equalizer APO 設定檔實際有沒有套用到目前的裝置（被其他等化器程式改過、或被調兩次時提示，按「一鍵修復」）
- 電腦版偵測 Tidal 輸出到別的裝置時提示 EQ 沒套用到
- 耳機模擬：旗艦多 4 款（HIFIMAN Arya、Audeze LCD-4、Focal Clear、Sony MDR-CD900ST）、熱門多 9 款（HD 560S、HD 58X、DT 770 Pro、AKG K371、K701、SHP9500、Porta Pro、Meze 99 Classics、Sony XM6）
- 新分頁「平價耳機」：水月雨 Chu／Aria／Starfield／KXXS、Truthear、7Hz、Tin HiFi T2、Etymotic ER2XR、final E1000／E3000 等 15 款因為調音出名的平價耳機（耳塞量測，近似）
- 新曲風：R&B、後朋克／冷波；「電子／嘻哈」改成「嘻哈」並加上饒舌咬字
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
- 電腦版殘響有時會整段消失：解碼器睡眠、重新插拔那一下偵測不到取樣率時，殘響會被拿掉，之後同樣的取樣率回來也不會補回。現在直接用已經做好的殘響檔
- 電腦版「恢復預設」也會關掉直通模式（以前按了看起來沒反應）
- 有幾個風格的設定跟別的完全一樣（流行／搖滾＝只校正、頭外定位＝60 年代搖滾、電子／嘻哈＝多低音族群、古典＝小聲聆聽）：合併或做出實際差別（古典加上音樂廳殘響）
- 電腦版視窗在大螢幕上下緣可能超出螢幕一點點（沒把標題列算進去）

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

[未發佈]: https://github.com/Benjaminwz/headphone-tuner/compare/v1.7.0...HEAD
[1.7.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.7.0
[1.6.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.6.0
[1.5.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.5.0
[1.4.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.4.0
[1.3.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.3.0
[1.2.1]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.2.1
[1.2.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.2.0
[1.1.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.1.0
[1.0.0]: https://github.com/Benjaminwz/headphone-tuner/releases/tag/v1.0.0
