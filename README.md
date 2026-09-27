# 耳機調音台

繁體中文介面的耳機等化器（Windows）。任何耳機一鍵校正到研究上最多人喜歡的 Harman 目標，
再從 50 多種依專業資料做的風格裡挑。整台電腦的聲音都有效（音樂串流、YouTube、遊戲），關掉視窗也照樣生效。

## 特色

- **任何耳機**：輸入型號搜尋，自動從 [AutoEQ](https://github.com/jaakkopasanen/AutoEq) 下載校正（6000 多款，最多 3 份不同單位的量測，可選平均）
- **風格都有根據，不靠感覺**：Harman 聆聽研究、ISO 226 等響曲線、ANSI S3.5 語音清晰度、bs2b 交叉饋送、Beranek 音樂廳殘響、
  旗艦／熱門耳機的量測反推（HD 800 S、Susvara、大奧、AirPods Max、Sony XM5…）
- **音量固定**：自動預留音量空間，切換風格、開關 EQ 音量都一樣，比較音質才公平，也不會破音
- **空間感**：聲場寬度、交叉饋送（像聽喇叭）、錄音室／音樂廳殘響、左右平衡＋測試音
- **輸出解析度**：直接切換送給解碼器的位元深度、取樣率
- **你的歌單**：有用 Tidal 的話，會分析你的收藏（只在本機讀），替特別大聲、特別小聲、容易爆音、有損音質的歌各做一個設定
- **快捷鍵**：Ctrl+Alt+E 開關 EQ、Ctrl+Alt+PgUp／PgDn 換風格（在其他程式裡也能用）

## 安裝

需要 Windows 10／11、[Python](https://www.python.org/downloads/)（安裝時勾選 Add python.exe to PATH）、
[Equalizer APO](https://sourceforge.net/projects/equalizerapo/)（免費的等化器核心）。

1. 到 [Releases](../../releases) 下載 zip，解壓縮
2. 雙擊 **安裝.bat**：自動裝好需要的套件、在桌面建立捷徑並打開調音台
3. 第一次打開會請你選耳機：輸入型號，點兩下就好

詳細說明、移除方法請看 [說明.txt](說明.txt)。

## 授權

MIT。耳機校正資料來自 AutoEQ（MIT）。
