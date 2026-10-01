<div align="center">

<img src="docs/icon-192.png" width="96" alt="耳機調音台">

# 耳機調音台 · Headphone Tuner

**任何耳機，一鍵校正到 Harman 目標，再挑一個合你胃口的聲音。**
整台電腦的聲音都有效，繁體中文介面，免費、不用註冊。

[![Release](https://img.shields.io/github/v/release/Benjaminwz/headphone-tuner?color=d96a2b&label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC)](../../releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%C2%B7%20Android%20%C2%B7%20Web-lightgrey)](#選擇你的版本)
[![Check](https://github.com/Benjaminwz/headphone-tuner/actions/workflows/check.yml/badge.svg)](../../actions/workflows/check.yml)

[⬇️ 下載](../../releases/latest) · [🌐 網頁版](https://benjaminwz.github.io/headphone-tuner/) · [📖 使用說明](說明.txt) · [📝 更新紀錄](CHANGELOG.md)

</div>

---

## 選擇你的版本

| | 電腦版（Windows） | 手機版（Android） | 網頁版（iPhone / iPad / 任何瀏覽器） |
| --- | --- | --- | --- |
| **作用範圍** | 整台電腦的聲音 | 整支手機（或接上各個播放 App） | 匯出給解碼器／耳擴，或用自己的音樂檔試聽 |
| **耳機校正（AutoEQ）** | ✅ 6000 多款 | ✅ | ✅ |
| **50 多種風格、細調、按住聽原音** | ✅ | ✅ | ✅ |
| **聲場寬度、交叉饋送、殘響** | ✅ | — | — |
| **藍牙耳機自動切換、快捷鍵、你的歌單** | ✅ | 藍牙／USB 解碼器可用 | — |
| **取得方式** | [安裝精靈](../../releases/latest) | [APK](../../releases/latest) | [直接開啟](https://benjaminwz.github.io/headphone-tuner/) |

<div align="center">
<img src="docs/img/web-preview.png" width="760" alt="網頁版畫面">
<br><sub>網頁版畫面（電腦版與手機版是同一套暖色系設計）</sub>
</div>

## 特色

- **任何耳機**：輸入型號搜尋，自動從 [AutoEQ](https://github.com/jaakkopasanen/AutoEq) 下載校正（6000 多款，最多 3 份不同單位的量測，可選平均）；資料庫沒量過的型號（例：Sony MDR-XB400）用同系列兄弟機推估
- **風格都有根據，不靠感覺**：Harman 聆聽研究、ISO 226 等響曲線、ANSI S3.5 語音清晰度、bs2b 交叉饋送、Beranek 音樂廳殘響、旗艦／熱門耳機的量測反推（HD 800 S、Susvara、大奧、AirPods Max、Sony XM5…）
- **藍牙耳機**：每個輸出裝置各自記住自己的耳機和調音；藍牙耳機一連上，Windows 切過去，調音台也自動跟著切（調音台沒開也照樣套用它自己的設定）。藍牙預設「音量優先」，不會太小聲；通話模式、還沒接上 EQ 都會提示怎麼處理
- **音量固定**：自動預留音量空間，切換風格、開關 EQ 音量都一樣，比較音質才公平，也不會破音
- **空間感**：聲場寬度、交叉饋送（像聽喇叭）、錄音室／音樂廳殘響、左右平衡＋測試音
- **輸出解析度**：直接切換送給解碼器的位元深度、取樣率
- **你的歌單**：有用 Tidal 的話，會分析你的收藏（只在本機讀），替特別大聲、特別小聲、容易爆音、有損音質的歌各做一個設定
- **好上手**：按住「按住聽原音」立刻比較差別、搜尋框打字找風格、看不懂的名稱滑鼠移上去就有白話說明、調壞了按「上一步」（Ctrl+Z）、右上角「怎麼用」六步驟教學
- **匯出給手機**：把耳機校正＋細調存成 AutoEQ 的 GraphicEQ 格式，手機的等化器 App 也能用同一組聲音
- **快捷鍵**：Ctrl+Alt+E 開關 EQ、Ctrl+Alt+PgUp／PgDn 換風格（在其他程式裡也能用）
- **暖色系介面**；螢幕比較小（例如筆電 150% 縮放）會自動縮小，不會超出螢幕

## 快速開始（Windows）

1. 安裝 [Equalizer APO](https://sourceforge.net/projects/equalizerapo/)（免費的等化器核心）。安裝最後勾選你的耳機用的輸出裝置，裝完**重新開機**。
2. 到 [Releases](../../releases/latest) 下載 `HeadphoneTuner-Setup-版本.exe`，一直按下一步。
   不用先裝 Python（會自動下載調音台專用的一份，不影響電腦裡其他程式），也不用系統管理員權限。
3. 第一次打開會請你選耳機：輸入型號，點兩下就好。右上角顯示「EQ 已接上」就代表聲音有經過調音。

> 要求：Windows 10／11。解除安裝時會把 Equalizer APO 的設定恢復原狀。

**免安裝版**：下載 `headphone-tuner-版本.zip`，解壓縮後雙擊「安裝.bat」（需要先裝 [Python](https://www.python.org/downloads/)）。
詳細說明、移除方法請看 [說明.txt](說明.txt)。

## 手機版（Android）

到 [Releases](../../releases/latest) 下載 `HeadphoneTuner-Android-版本.apk`，在手機上打開安裝（第一次要允許「安裝未知應用程式」）。Android 10 以上。

- 用 Android 內建的 DynamicsProcessing 等化器（64 段）套到**整支手機**；有些手機不允許，會自動改成接上各個播放 App
- 接 USB 解碼器、藍牙耳機都能用；開機自動恢復
- 只調音色（耳機校正＋風格＋細調）；聲場寬度、交叉饋送、殘響是電腦版才有
- Tidal 請不要打開「獨佔模式」「強制音量」這類讓外接解碼器直接輸出的選項，不然會繞過等化器

## 網頁版（iPhone、iPad、任何瀏覽器）

**打開：https://benjaminwz.github.io/headphone-tuner/**（Safari 按「分享 → 加入主畫面」就像 App 一樣）

iPhone 不允許任何 App 改其他 App（例如 Tidal）的聲音，所以網頁版是：同一套耳機校正＋風格＋細調，
**匯出成參數等化（5／8／10／15 段，自動擬合）給有內建等化器的解碼器／耳擴**（聲音在解碼器裡處理，iPhone 上的 Tidal 也有效），
另外可以**用自己的音樂檔直接試聽**（含按住聽原音）。資料只存在你的瀏覽器裡。

## 常見問題

<details>
<summary><b>為什麼開啟後音量比較小？</b></summary>

為了切換任何風格都不會破音，調音台會固定預留一段音量空間（依你的耳機自動算，大多 8–12 dB），
所以整體會小一點，把音量轉大一點就好。好處是切換風格、開關 EQ 時音量都一樣，比較音質才公平。
</details>

<details>
<summary><b>右上角顯示「還沒接上」怎麼辦？</b></summary>

按旁邊的按鈕，在跳出的視窗勾選你的輸出裝置 → 確定 → 重新開機。
</details>

<details>
<summary><b>藍牙耳機沒有效果？</b></summary>

在 Equalizer APO 的設定視窗勾選「Troubleshooting options」，選「Install as SFX/EFX (experimental)」，按確定後重新開機。
藍牙的音質（SBC、AAC、aptX…）由 Windows 自動決定，所以「輸出解析度」對藍牙不能用。
</details>

<details>
<summary><b>找不到我的耳機型號？</b></summary>

可以按「找不到，先不校正」，風格一樣能用。也歡迎[開 Issue](../../issues/new/choose) 告訴我型號。
</details>

<details>
<summary><b>怎麼移除、還原？</b></summary>

用安裝精靈裝的：Windows「設定 → 應用程式」解除安裝「耳機調音台」，會自動還原 Equalizer APO 的設定。
免安裝版的作法見 [說明.txt](說明.txt)。
</details>

## 自己建置

| 目標 | 指令 |
| --- | --- |
| 電腦版直接執行 | `python 耳機調音台.pyw`（`--config-dir <資料夾>` 可寫到別的設定資料夾測試，不會動到真正的音效設定） |
| 安裝精靈 | `python installer/build.py v1.2.3`（需要 Inno Setup 6，加 `--test` 做測試用安裝檔） |
| Android APK | `python android/gen_data.py`（從電腦版匯出風格資料），再執行 `android/build_apk.ps1`（需要 JDK 17、Android SDK 35，不用 Gradle） |
| 檢查（CI 同款） | `python tools/check.py` |

電腦版改了風格之後，重跑 `android/gen_data.py` 並把 `android/assets/data.json` 複製為 `docs/data.json`，手機版和網頁版就會跟著更新。
貢獻方式請看 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 授權與致謝

MIT，詳見 [LICENSE](LICENSE)。耳機校正資料來自 [AutoEQ](https://github.com/jaakkopasanen/AutoEq)（MIT），
等化器核心是 [Equalizer APO](https://sourceforge.net/projects/equalizerapo/)。
