# -*- coding: utf-8 -*-
"""耳機調音台（通用版）：用中文介面調 Equalizer APO。任何耳機、任何輸出裝置都能用。
耳機校正從 AutoEQ 資料庫下載（目標 Harman）；改動會即時寫進 Equalizer APO 的設定檔，關掉視窗仍然有效。
測試用：加上 --config-dir <資料夾> 可以改寫別的設定資料夾，不會動到真正的音效設定。"""
import cmath
import ctypes
import ctypes.wintypes
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import urllib.request
import uuid
import winreg
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
ICON_PATH = os.path.join(APP_DIR, "tuner.ico")
APP_ID = "HeadphoneTuner.Panel"  # 工作列用自己的圖示（不跟 Python 混在一起）
OUT_NAME = "tuner_current.txt"
HP_DIR = os.path.join(APP_DIR, "耳機資料")  # 耳機清單、下載的校正檔快取
AUTOEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
APO_URL = "https://sourceforge.net/projects/equalizerapo/"
# config.txt 裡由調音台管理的區塊（只給選定的裝置用）
BLOCK_BEGIN = "# ==== 耳機調音台：自動管理的區塊，請勿修改 ===="
BLOCK_END = "# ==== 耳機調音台區塊結束 ===="
DUMMY_GUID = "{00000000-0000-0000-0000-000000000000}"
APO_CLSID = "EACD2258"
MM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
NAME_KEY = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"  # 介面名稱（例：TOPPING USB DAC）
DESC_KEY = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"  # 裝置種類（例：喇叭、耳機）
FORMAT_KEY = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"

# 配色：淺色系，白卡片＋深藍字＋寶藍色重點（跟藍色大肥魚同一套）
BG, HEADER, PANEL, LINE = "#EEF3FB", "#FFFFFF", "#FFFFFF", "#DCE5F3"
PILL, PILL_HOVER, TRACK = "#EEF3FB", "#E1EAF8", "#DCE5F3"
TEXT, SUB, VALUE = "#0F2A5C", "#6B7A99", "#1E5BD8"
ACCENT, ACCENT_HI, FILL = "#1E5BD8", "#3B74E6", "#E6EEFD"
GREEN, GREEN_BG, ORANGE, ORANGE_BG = "#1C8C5E", "#E3F5EC", "#C8671A", "#FDF0E3"
GOLD, GOLD_BG, CD_FG, CD_BG = "#A16207", "#FEF3C7", "#1E5BD8", "#E6EEFD"
GRID_MINOR, ZERO_LINE, KNOB_EDGE = "#F1F5FB", "#B8C7E3", "#C9D5EA"
# 字體：實際用哪個在 pick_fonts() 依電腦上有的決定（中文 Noto Sans TC、數字 Inter）
FONT = FONT_MED = "Microsoft JhengHei UI"
NUM = "Segoe UI"

# 耳機校正：使用者選好耳機後，從 AutoEQ 下載最多 3 份不同來源的量測（目標 Harman），由 set_headphone() 填入
BASES = {"none": ("不校正（耳機原味）", [])}
SOURCE_ORDER = ["oratory1990", "crinacle", "Rtings", "Innerfidelity", "Super Review", "Headphone.com Legacy"]


def set_headphone(hp):
    """依耳機資料重建 BASES：第一份來源＝推薦、其餘各一個、兩份以上再加「多份平均」"""
    srcs = (hp or {}).get("sources") or []
    BASES.clear()
    for key, (label, fl) in zip(("autoeq", "src2", "src3"), srcs):
        BASES[key] = (f"{label}（推薦）" if key == "autoeq" else f"{label} 量測", [tuple(f) for f in fl])
    if len(srcs) >= 2:  # 每個濾波器增益 ÷ 份數疊起來 ≈ 各條校正曲線（dB）的平均，比較不會被單一量測設備帶偏
        BASES["avg"] = ("多份平均（最不偏）", [(t, f, g / len(srcs), q) for _l, fl in srcs for t, f, g, q in fl])
    BASES["none"] = ("不校正（耳機原味）", [])


def default_base():
    return "autoeq" if "autoeq" in BASES else "none"


# 細調滑桿：名稱, 類型, 頻率, Q, 說明（低頻 105 Hz、高頻 10 kHz 跟 Harman／AutoEQ 的定義一樣）
BANDS = [
    ("低頻", "LSC", 105, 0.7, "鼓、貝斯的量感"),
    ("厚度", "PK", 250, 1.0, "聲音飽不飽滿"),
    ("人聲", "PK", 1500, 1.0, "人聲、樂器主體"),
    ("臨場感", "PK", 3500, 1.2, "清晰、貼近的感覺"),
    ("高頻", "HSC", 10000, 0.7, "亮度、空氣感"),
]
# 風格全部依專業資料。目標曲線類＝「該目標 − Harman 2018」的差異，擬合到細調滑桿。
# 名稱, 細調值, 聲場寬度(%), 交叉饋送等級, 依據
RESEARCH = [
    ("只校正", [0, 0, 0, 0, 0], 0, 0,
     "Harman 2018 目標：盲聽測試中 64% 聽眾的首選（Olive, Acoustics Today 2022）"),
    ("多低音族群", [4, 0, 0, 0, 0], 0, 0,
     "15% 聽眾偏好比 Harman 多 4–6 dB 低音（同上研究；取 4 dB 以免破音）"),
    ("少低音族群", [-2, 0, 0, 0, 0], 0, 0,
     "21% 聽眾偏好比 Harman 少 2 dB 低音（同上研究）"),
    ("女性聽眾偏好", [-1, 0, 0, 0, -2], 0, 0,
     "女性平均比男性少約 1 dB 低音、2 dB 高音（Olive & Welti, AES 2015）"),
    ("擴散場中性", [-6, 0, 2.5, 3.5, 6], 0, 0,
     "ISO 11904 擴散場：傳統錄音室中性參考（AutoEQ 資料擬合，誤差 0.7 dB）"),
    ("oratory1990", [-4.5, 1.5, 1, 0.5, 2], 0, 0,
     "oratory1990「optimum hifi」專業目標（AutoEQ 資料擬合，誤差 0.35 dB）"),
    ("小聲聆聽", [4.5, 2, -0.5, -0.5, 1.5], 0, 0,
     "ISO 226 等響曲線：比錄音室參考（80 phon）小聲 10 dB 時的補償（誤差 0.3 dB）"),
    ("瞬態最好", [-2, -2, 0, 1.5, 0], 0, 0,
     "只校正＋不加任何會拖時間的處理（殘響、交叉饋送都關）；低頻、250 Hz 各 −2 dB：低頻的後遮蔽可達約 200 ms，"
     "會蓋掉下一個起音（Zwicker & Fastl；−2 dB 是 Olive 2022 少低音族群仍偏好的量）；3.5 kHz +1.5 dB 補起音（撥弦、鼓棒）；"
     "濾波器都是最小相位、Q ≤ 1.2，沒有前振鈴，後振鈴 < 0.1 ms"),
    ("喇叭感外化", [0, 0, 0, 0, 0], 0, 2,
     "bs2b 交叉饋送 Chu Moy 參數（700 Hz / 6 dB）：讓聲音跑到頭外面，像聽喇叭"),
]
# 曲風：各曲風的專業數據。頻譜本身差異小（Pestana 2013：各曲風母帶都朝同一條目標頻譜製作），
# 真正差很多的是音量：古典、爵士動態大、平均音量低（Kirchberger & Russo 2016；Katz K-System），
# Tidal 音量平衡關閉時會比流行小聲 → 用 ISO 226 等響曲線補償
GENRE = [
    ("流行／搖滾", [0, 0, 0, 0, 0], 0, 0,
     "Harman 目標的盲聽曲目以流行、搖滾為主；Pestana 2013（AES）：各曲風母帶都朝同一條目標頻譜製作"),
    ("超級低音衝擊", [4.5, -0.5, -3.5, -3, -4.5], 0, 0,
     "夜店／演唱會 100 dB 在家 80 dB 聽的 ISO 226 等響差，只取 500 Hz 以下（60 Hz 約 +8 dB）；預留空間只夠低頻 +4.5 dB → "
     "其餘頻段一起降約 3 dB，讓低音比中頻多 6.3 dB（≈ Olive 2022 愛低音族群偏好的上限 +6 dB）；代價是整體小約 3 dB，確保不破音"),
    ("蒸汽波／City Pop", [2, 0, 0, 0, -3], 0, 1,
     "卡帶（Type I）頻寬約 30 Hz–15 kHz（±3 dB）→ 高頻 −3 dB；磁帶磁頭的低頻凸起（head bump）→ 低頻 +2 dB；"
     "蒸汽波的 mallsoft 就是在模擬挑高購物中心的殘響 → 約 2 秒的大空間殘響（沿用音樂廳前排的 Beranek 參數）＋輕交叉饋送"),
    ("電子／嘻哈", [4, 0, 0, 0, 0], 0, 0,
     "Harman 研究：15% 聽眾偏好多 4–6 dB 低音，年輕聽眾也偏好更多低音（Olive & Welti 2015）"),
    ("爵士經典", [1.5, 0.5, 0, 0, 0.5], 0, 3,
     "老爵士母帶普遍比現代流行小聲約 3 dB → ISO 226 等響補償；50–60 年代爵士立體聲常把鼓和管樂硬分左右"
     "（交叉饋送就是為此發明，Bauer 1961）→ bs2b 最強；加 ITU-R BS.1116 小房間殘響 0.25 秒"),
    ("電影／遊戲配樂", [2.5, 1, 0, 0, 1], 20, 1,
     "電影混音標準監聽 85 dB（SMPTE RP 200），在家約 80 dB 聽 → ISO 226 等響補償；加寬 20%＋輕交叉饋送"),
    ("爵士", [2.5, 1, 0, -0.5, 1], 0, 0,
     "爵士母帶約 K-14，比現代流行（約 −8 LUFS）小聲約 5 dB → ISO 226 等響補償（誤差 0.2 dB）"),
    ("古典", [4.5, 2, -0.5, -0.5, 1.5], 0, 0,
     "古典動態最大（Kirchberger & Russo 2016），母帶約 K-20，比流行小聲約 10 dB → ISO 226 等響補償（誤差 0.3 dB）"),
    ("老唱片雜音", [0, 0, 0, 0, -6], 0, 0,
     "電氣錄音時代 78 轉唱片頻寬約 50 Hz–6 kHz（Western Electric 1925 系統），更高只剩表面雜音 → 高頻壓到 −6 dB（16 kHz −6 dB、6 kHz 以下幾乎不變）"),
    ("人聲／Podcast", [-1.5, -1, 2, 2, 0], 0, 0,
     "ANSI S3.5 語音清晰度：1–4 kHz 占 72% 重要度；低頻會往上遮蔽人聲，所以收一點"),
    ("女毒", [-1, -0.5, 1.5, 2.5, 1.5], 0, 0,
     "沒有正式研究：依 ANSI S3.5 清晰度區加強 1.5–4 kHz，不動齒音區 5–8 kHz"),
]
# 殿堂聲場：真正的空間感來自殘響與兩耳差異（名稱, 細調, 加寬, 交叉饋送, 依據）；殘響空間見 STYLE_ROOM
ROCK = [  # 搖滾細分：依年代／子類；響度差是實測一份約 1,500 首收藏各類的中位數
    ("60 年代搖滾", [0, 0, 0, 0, 0], 0, 3,
     "60 年代立體聲常把人聲、樂器硬分左右；交叉饋送就是為此發明的（Bauer 1961, JAES）→ bs2b 最強"),
    ("70–80 年代硬搖滾", [4.5, 3.5, -0.5, -1, 3], 0, 2,
     "體育館演唱會約 100 dB（WHO 2022 場館上限；Deep Purple 1972 年曾以 117 dB 列入金氏紀錄）"
     "ISO 226 補償 100→80.9 phon（受預留空間與 Olive 2022 +6 dB 上限限制）＋bs2b 交叉饋送（聲音來自前方喇叭）"),
    ("金屬", [-0.5, -2, 0, 2, 0], 0, 0,
     "破音吉他牆的 250 Hz 會往上遮蔽其他樂器（Zwicker & Fastl）→ −2 dB；撥弦、大鼓踏板的「喀」在 2–4 kHz（ANSI S3.5 清晰度權重最高）→ +2 dB；"
     ""),
    ("龐克", [-3.5, -2.5, 0, 1.5, -0.5], 0, 0,
     "龐克速度約 180 BPM，八分音符每 170 ms 一下，比低音的後遮蔽（約 200 ms，Zwicker & Fastl）還短 → 低頻、250 Hz 各 −2 dB 讓每一下分得開，3.5 kHz +1.5 dB 補起音；"
     ""),
    ("英搖／日搖", [-1, -0.5, 0, -2, -0.5], 0, 0,
     "Oasis、SiM、King Gnu 這類母帶很大聲："),
    ("前衛／迷幻", [1.5, 0.5, 0, 0, 0.5], 20, 0,
     "Pink Floyd 這類母帶動態大：；刻意設計的左右移動效果 → 不用交叉饋送、再加寬 20%"),
    ("華語搖滾", [0, 0, 1.5, -1, 0], 0, 0,
     "中文是聲調語言，字義靠基頻與低次諧波（粵語 SII 研究：中低頻權重比英文高）→ 人聲 1.5 kHz +1.5 dB"),
    ("現場搖滾", [4.5, 2, -0.5, -0.5, 1.5], 0, 2,
     "ISO 226：現場約 90 phon、家裡 80 phon 的等響補償（誤差 0.3 dB）＋bs2b 交叉饋送（現場是聽前方的喇叭）"),
    ("搖滾 Grado 味", [-4.5, 2.5, 1.5, -4, 0], 0, 0,
     "Grado SR325x（搖滾耳機代表）音色走向（oratory1990 量測反推，誤差 1.9 dB）"),
    ("搖滾 V 型", [-1.5, 3, -0.5, 3.5, 6], 0, 0,
     "Beyerdynamic DT 990 Pro（金屬樂常用）音色走向（oratory1990 量測反推，誤差 2.0 dB）"),
    ("搖滾錄音室", [1, 1, 0, -1.5, 3.5], 0, 0,
     "Audio-Technica ATH-M50x（最多人用的錄音室耳機）音色走向（oratory1990 量測反推，誤差 1.6 dB）"),
]
STAGE = [
    ("錄音室監聽", [0, 0, 0, 0, 0], 0, 2,
     "ITU-R BS.1116 標準聆聽室殘響 0.25 秒＋bs2b 交叉饋送；房間反射能讓聲音到頭外（Catic 2015, JASA）"),
    ("音樂廳前排", [0, 0, 0, 0, 0], 0, 1,
     "Beranek 頂級音樂廳數據：殘響 2.0 秒、低頻比 1.2、首次反射 15 ms；前排直達聲多（直達/殘響比 +6 dB）"),
    ("音樂廳中段", [0, 0, 0, 0, 0], 0, 1,
     "同一個音樂廳往後坐：直達/殘響比比前排少 3 dB（約遠 1.4 倍）→ 距離感與舞台深度增加（Zahorik 2002）"),
    ("寬廣舞台", [0, 0, 0, 0, 0], 25, 0,
     "加寬 25%：降低兩耳訊號相關性（IACC）→ 聲源變寬（Beranek 音樂廳研究的 ASW 指標）"),
    ("分離度拉滿", [-2, -2, 0, 2, 2], 40, 0,
     "加寬到上限 40%（兩耳相關性最低 → 聲源最開，Beranek ASW）＋不用交叉饋送（它會混合左右）；"
     "低頻、250 Hz 各 −2 dB 減少低頻往上遮蔽中高頻（Zwicker & Fastl；−2 dB 是 Olive 2022 少低音族群仍偏好的量）；"
     "臨場感、高頻 +2 dB（ANSI S3.5 清晰度權重最高的頻段）"),
    ("頭外定位", [0, 0, 0, 0, 0], 0, 3, "bs2b 交叉饋送最強參數（700 Hz / 4.5 dB）：聲音最不會卡在腦中"),
    ("HD 800 S 大空間", [-4.5, 4, -1.5, 0.5, 5.5], 15, 1,
     "HD 800 S 音色走向（oratory1990 量測反推）＋交叉饋送（輕）＋加寬 15%"),
]
STYLE_ROOM = {"錄音室監聽": 1, "音樂廳前排": 2, "音樂廳中段": 3, "蒸汽波／City Pop": 2, "爵士經典": 1}  # 風格 → 殘響空間
# 殿堂／大眾：把該耳機的 AutoEQ 校正反過來＝它相對 Harman 的聲音走向，擬合到細調滑桿。
# 只模擬音色走向（音場大小、解析力是硬體本身的，EQ 模擬不了）；標 * 的加強幅度已限制以免破音
LEGEND = [(n, v, 0, 0, s) for n, v, s in (
    ("大奧二代 HE 1", [-1.5, 2, -1, 1, 6], "Sennheiser HE 1 Orpheus 2 靜電旗艦：低頻接近 Harman、高頻延伸極好（oratory1990 量測反推，誤差 0.7 dB）"),
    ("大奧一代 HE 90", [-5.5, 1, 0, 1.5, 2], "Sennheiser HE 90 Orpheus 初代靜電傳奇：低頻少、中高頻清透（oratory1990 量測反推，誤差 0.7 dB）"),
    ("HD 800 S", [-4.5, 4, -1.5, 0.5, 5.5], "Sennheiser HD 800 S 參考級旗艦：低頻少、高頻亮（oratory1990 量測反推，誤差 1.0 dB）"),
    ("Focal Utopia", [-5, 1.5, 0, -2.5, -3], "Focal Utopia 旗艦動圈：低頻少、高頻收斂（oratory1990 量測反推，誤差 1.5 dB）"),
    ("Stax SR-009S", [-6, -2, 0.5, -3.5, -2], "Stax SR-009S 靜電旗艦：低頻少、中高頻內斂（oratory1990 量測反推，誤差 1.8 dB）"),
    ("Susvara", [-3.5, 3.5, -2, 0.5, 2.5], "HIFIMAN Susvara 平板旗艦：低頻少、中低頻飽滿（crinacle 量測反推，誤差 1.1 dB）"),
    ("HE1000se", [-3, 3.5, -2.5, 4.5, 6], "HIFIMAN HE1000se 平板旗艦：明亮、細節多（oratory1990 量測反推，誤差 1.2 dB）"),
    ("Audeze LCD-X", [-5, 2, 0.5, -6, 2], "Audeze LCD-X 錄音室平板：3 kHz 內收、聽感厚實（oratory1990 量測反推，誤差 1.0 dB）"),
    ("HD 600", [-5.5, 1.5, 0, -0.5, 0], "Sennheiser HD 600 三十年傳奇參考：低頻少、中頻自然（oratory1990 量測反推，誤差 1.1 dB）"),
    ("HD 650", [-5.5, 2, 0, -0.5, -2], "Sennheiser HD 650 傳奇溫暖型：低頻少、高頻柔（oratory1990 量測反推，誤差 1.2 dB）"),
    ("MDR-7506", [-0.5, 0, -0.5, 5, 0], "Sony MDR-7506 錄音室業界標準：中高頻突出、好抓細節（oratory1990 量測反推，誤差 1.5 dB）"))]
POPULAR = [(n, v, 0, 0, s) for n, v, s in (
    ("AirPods Max", [1.5, 1, 0.5, -6, 0.5], "Apple AirPods Max：低頻足、3–4 kHz 內收、聽感柔和（oratory1990 量測反推，誤差 1.3 dB）"),
    ("Sony XM5", [4.5, 5, -3, 4, -1], "Sony WH-1000XM5：低頻加強的熱門聽感（oratory1990 量測反推，誤差 2.1 dB；加強幅度已限制以免破音）"),
    ("Sony XM4", [4.5, 4.5, -2, -1, 2.5], "Sony WH-1000XM4：低頻厚實（oratory1990 量測反推，誤差 1.8 dB；加強幅度已限制以免破音）"),
    ("Bose QC45", [3, 2.5, -0.5, 2.5, 5], "Bose QuietComfort 45：低頻足、高頻亮（oratory1990 量測反推，誤差 1.3 dB）"),
    ("Momentum 4", [4.5, 5, -2, -0.5, 2], "Sennheiser Momentum 4：低頻很多（oratory1990 量測反推，誤差 2.2 dB；加強幅度已限制以免破音）"),
    ("Beats Studio Pro", [1, -5, 1.5, 0.5, 2], "Beats Studio Pro：中低頻乾淨、高頻亮（Rtings 量測反推，誤差 1.5 dB）"))]
# 白話介紹：聽起來怎樣＋適合聽什麼（聽感依曲線描述；「適合」是一般聆聽經驗，不是研究結論）
PLAIN = {
    "只校正": "最平衡、最多人喜歡的標準聲音。什麼音樂都適合",
    "多低音族群": "低音更飽、更有衝擊力。適合流行、電子、嘻哈",
    "少低音族群": "低音收一點，清爽乾淨。適合人聲、民謠、長時間聽",
    "女性聽眾偏好": "低音、高音都柔一點，比較溫和。適合抒情、輕音樂",
    "擴散場中性": "錄音室式中性，低音少、高音亮。適合古典、仔細聽錄音",
    "oratory1990": "專業工程師的調音，自然耐聽。什麼音樂都適合",
    "小聲聆聽": "音量開小時把低音和高音補回來。適合深夜、背景音樂",
    "瞬態最好": "起音乾脆、收得快，低音緊不拖尾。鼓、吉他、鋼琴的衝擊感最清楚。適合搖滾、金屬、爵士鼓",
    "喇叭感外化": "聲音從腦袋裡跑到前方，像聽喇叭。適合長時間聽、老錄音",
    "流行／搖滾": "標準平衡的聲音。流行、搖滾、華語、K-pop 都適合",
    "現場搖滾": "補回現場大聲聽的低音衝擊和高音，聲音在前方。適合現場錄音、樂團",
    "搖滾 Grado 味": "低音收、中頻往前，吉他和人聲很有顆粒感。適合經典搖滾、英搖、龐克",
    "搖滾 V 型": "低音有力、高音很亮，鼓和鈸很有衝勁。適合金屬、硬式搖滾",
    "搖滾錄音室": "微 V 型、低音紮實、高音亮。各種搖滾、樂團都適合",
    "電子／嘻哈": "低音更飽、更有衝擊力。適合電子、EDM、嘻哈、饒舌",
    "爵士": "補回小音量聽不到的低音和空氣感。適合爵士、藍調",
    "古典": "補回古典小聲段落的低音和高音。適合交響、鋼琴、歌劇",
    "人聲／Podcast": "人聲往前、咬字清楚。適合歌手、Podcast、有聲書",
    "老唱片雜音": "78 轉唱片、黑膠翻錄的老錄音（比莉·哈樂黛那個年代）：壓掉高頻的沙沙聲、爆豆聲，音樂本身幾乎不受影響",
    "60 年代搖滾": "披頭四、滾石、Hendrix、CCR、Bob Dylan：老錄音左右分太開，這個讓它自然、不卡在單耳",
    "70–80 年代硬搖滾": "齊柏林、Deep Purple、Queen、AC/DC、槍與玫瑰、Scorpions：補回體育館演唱會的低音衝擊",
    "金屬": "Metallica、Sabaton：吉他牆不糊，撥弦和大鼓的顆粒感更清楚",
    "龐克": "The Lurkers、Joe Strummer：低音收緊、每一下都乾脆，速度感最好",
    "英搖／日搖": "Oasis、Radiohead、SiM、King Gnu、進擊的巨人主題曲：母帶很大聲，這個讓它不轟、不刺",
    "前衛／迷幻": "Pink Floyd、Yes、Genesis：補回小聲母帶的低音，左右移動的音效更開闊",
    "華語搖滾": "Beyond、五月天、羅大佑、滅火器、草東：歌詞咬字更清楚，破音不刺",
    "超級低音衝擊": "低音像在夜店、演唱會現場一樣大，胸口有衝擊。適合電音、嘻哈、電影音效（整體會小一點，DAC 音量調大約 3 dB）",
    "蒸汽波／City Pop": "當山瞳、竹內瑪莉亞、松原美樹、Yung Bae、Corn Wave：像用卡帶在空蕩的購物中心裡放，暖、朦朧、有空間感",
    "爵士經典": "辛納屈、比莉·哈樂黛、邁爾士·戴維斯、柯川：老爵士左右分太開又偏小聲，這個讓樂手自然地在你前方，像在小爵士俱樂部裡聽",
    "電影／遊戲配樂": "補回戲院音量的低音衝擊，舞台更寬。適合電影原聲、遊戲配樂、史詩音樂",
    "女毒": "女聲甜、貼近耳邊、聽得到換氣。適合女歌手、爵士女聲",
    "錄音室監聽": "像坐在錄音室聽一對喇叭，聲音在前方。適合長時間聽、細聽混音",
    "音樂廳前排": "坐在音樂廳前排：清楚又有殿堂殘響。適合古典、交響、合唱",
    "音樂廳中段": "往後坐，舞台更深、更有空間感。適合交響、歌劇、管風琴",
    "寬廣舞台": "左右拉得很開、樂器分得清楚。適合流行、電影配樂、遊戲",
    "分離度拉滿": "左右拉到最開、低音不糊，每件樂器都分得清清楚楚。適合搖滾、流行、遊戲（很老的立體聲錄音可能太開）",
    "頭外定位": "聲音最像從前方傳來，不卡在腦中。適合老錄音、長時間聽",
    "HD 800 S 大空間": "HD 800 S 式的開闊高音＋大空間處理。適合古典、原聲、現場",
    "大奧二代 HE 1": "極致通透、高音延伸好、細節滿滿。適合古典、爵士、高解析錄音",
    "大奧一代 HE 90": "溫潤清透、低音含蓄。適合古典、人聲、室內樂",
    "HD 800 S": "空間感大、高音亮、細節多。適合古典、管弦、現場錄音",
    "Focal Utopia": "有力道、中頻紮實、高音不刺。適合搖滾、爵士",
    "Stax SR-009S": "輕盈細膩、高音柔和。適合古典、弦樂、人聲",
    "Susvara": "中低頻厚實、很大氣。適合交響樂、爵士、電影配樂",
    "HE1000se": "明亮開闊、細節多。適合古典、原聲樂器",
    "Audeze LCD-X": "厚實溫暖、不刺耳。適合搖滾、電子",
    "HD 600": "自然、中頻漂亮的經典聲音。適合人聲、民謠，什麼都能聽",
    "HD 650": "溫暖滑順、很耐聽。適合爵士、搖滾、長時間聽",
    "MDR-7506": "中高音突出、細節清楚。適合聽清楚歌詞、檢查錄音",
    "AirPods Max": "柔和、低音足、不刺耳。適合流行、日常聽",
    "Sony XM5": "低音澎湃、人聲稍微退後。適合流行、電子、通勤",
    "Sony XM4": "低音厚、聽感溫暖。適合流行、嘻哈",
    "Bose QC45": "低音足、高音亮、很有精神。適合流行、Podcast",
    "Momentum 4": "低音很多、很有氣勢。適合電子、嘻哈、EDM",
    "Beats Studio Pro": "中低頻乾淨、高音亮、節奏清楚。適合流行、嘻哈",
}
# 「你的歌單」分頁在啟動時依這台電腦的 Tidal 收藏產生（analyze_tidal），有才會出現
STYLE_GROUPS = [("研究依據", RESEARCH), ("曲風", GENRE), ("搖滾", ROCK), ("殿堂聲場", STAGE), ("旗艦耳機", LEGEND), ("大眾熱門", POPULAR)]
STYLES = [s for _name, group in STYLE_GROUPS for s in group]
FREQS = [20 * 1000 ** (i / 199) for i in range(200)]
AUTO = "自動 "  # 自動存檔的預設名稱開頭
# 固定預留的音量空間（dB）：不管切換哪個設定、開關 EQ，音量都一樣，方便比較音質。
# 依選的耳機自動算（update_headroom）：＝這支耳機的各種校正＋所有內建風格裡最大的加強
HEADROOM = 11.0
# 耳機交叉饋送（bs2b 三組標準參數）：名稱, 低頻側訊號衰減 dB, 轉折頻率 Hz
# 輕＝Jan Meier（650 Hz / 9.5 dB）、中＝Chu Moy（700 Hz / 6 dB）、強＝bs2b 預設（700 Hz / 4.5 dB）
CROSSFEED = [("關", 0.0, 700), ("輕", -6.0, 650), ("中", -9.6, 700), ("強", -11.9, 700)]
# 殘響空間：名稱, 中頻殘響 RT60(秒), 低頻比, 高頻比, 首次反射 ITDG(ms), 直達/殘響比 DRR(dB), 檔名
ROOMS = [("關", 0, 0, 0, 0, 0, ""),
         ("錄音室", 0.25, 1.0, 0.9, 3, 10, "studio"),         # ITU-R BS.1116 標準聆聽室
         ("音樂廳前排", 2.0, 1.2, 0.75, 15, 6, "hall_front"),  # Beranek 頂級音樂廳（維也納金色大廳約 2.0 秒）
         ("音樂廳中段", 2.0, 1.2, 0.75, 20, 3, "hall_mid")]    # 往後坐：直達/殘響比少 3 dB（約遠 1.4 倍，Zahorik 2002）


def room_file(cfg_dir, room, rate):
    """殘響檔（Equalizer APO 不會自動轉取樣率，所以依 DAC 目前取樣率做一份）；已經有就直接用"""
    _n, rt, br, tr, itdg, drr, key = ROOMS[room]
    name = f"reverb_{key}_v2_{rate}.wav"  # v2：兩耳相關性照真實聲場
    path = os.path.join(cfg_dir, name)
    if os.path.exists(path):
        return name
    import numpy as np
    n = int(rate * (itdg / 1000 + rt * max(br, 1) * 1.05))
    t = np.arange(n) / rate
    freqs = np.fft.rfftfreq(n, 1 / rate)
    rng = np.random.default_rng(7)  # 固定種子：每次做出來都一樣
    start = int(rate * itdg / 1000)
    # 兩耳相關性照真實擴散聲場（Lindevald & Benade）：sin(kd)/kd，耳距約 18 cm
    # → 低頻兩耳幾乎一樣（不會左右亂飄、變碎），約 1 kHz 以上才各自獨立（聲場寬、包圍感）
    common, left, right = (np.fft.rfft(rng.standard_normal(n)) for _ in range(3))
    coh = np.clip(np.sinc(2 * freqs * 0.18 / 343), 0, 1)
    specs = (np.sqrt(coh) * common + np.sqrt(1 - coh) * left, np.sqrt(coh) * common + np.sqrt(1 - coh) * right)
    # 殘響慢慢長出來（不是一開始就滿），避免跟原音疊出梳狀的顆粒感
    onset = 1 - np.exp(-np.maximum(t - itdg / 1000, 0) / max(rt * 0.01, 0.002))
    ir = np.zeros((n, 2))
    for ch, spec in enumerate(specs):
        tail = np.zeros(n)
        # 各頻段衰減速度不同；8 kHz 以上再快一點（空氣吸收），殘響尾巴才不會沙沙的
        for lo, hi, r in ((0, 500, rt * br), (500, 4000, rt), (4000, 8000, rt * tr), (8000, rate, rt * tr * 0.6)):
            tail += np.fft.irfft(np.where((freqs >= lo) & (freqs < hi), spec, 0), n) * np.exp(-6.91 * t / r)
        tail *= onset
        tail[:start] = 0
        tail *= math.sqrt(10 ** (-drr / 10) / (tail ** 2).sum())  # 依直達/殘響比調整殘響大小
        ir[:, ch] = tail
    ir[0, :] += 1.0  # 直達聲＝原音
    data = ir.astype("<f4").tobytes()
    head = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 3, 2, rate, rate * 8, 8, 32) + b"data" + struct.pack("<I", len(data)))
    for old in os.listdir(cfg_dir):  # 同一個空間其他取樣率的舊檔清掉
        if old.startswith(f"reverb_{key}_") and old != name:
            try:
                os.remove(os.path.join(cfg_dir, old))
            except OSError:
                pass
    with open(path, "wb") as fh:
        fh.write(head + data)
    return name


_ROOM_GAIN = {}


def room_gain(cfg_dir, name):
    """殘響在各頻率的最大增益（dB，對應 FREQS）。長殘響的頻率響應有很多尖峰，
    持續的音剛好落在尖峰上就會破音，所以防破音要用最壞的那個值"""
    if name not in _ROOM_GAIN:
        import numpy as np
        raw = open(os.path.join(cfg_dir, name), "rb").read()
        rate = struct.unpack("<I", raw[24:28])[0]
        ir = np.frombuffer(raw[44:], "<f4").reshape(-1, 2)
        freqs = np.fft.rfftfreq(len(ir), 1 / rate)
        mag = np.maximum(np.abs(np.fft.rfft(ir[:, 0])), np.abs(np.fft.rfft(ir[:, 1])))
        f = np.array(FREQS)
        edges = np.concatenate(([f[0] / 1.02], np.sqrt(f[:-1] * f[1:]), [f[-1] * 1.02]))
        idx = np.searchsorted(freqs, edges)
        _ROOM_GAIN[name] = [20 * math.log10(max(float(mag[a:max(b, a + 1)].max()), 1e-9))
                            for a, b in zip(idx[:-1], idx[1:])]
    return _ROOM_GAIN[name]


# 全域快捷鍵：id, 修飾鍵(Ctrl+Alt), 按鍵, 名稱, 說明
HOTKEYS = [(1, 0x2 | 0x1, 0x45, "Ctrl+Alt+E", "開關 EQ"),
           (2, 0x2 | 0x1, 0x22, "Ctrl+Alt+PgDn", "下一個風格"),
           (3, 0x2 | 0x1, 0x21, "Ctrl+Alt+PgUp", "上一個風格")]
# 常見的輸出格式（裝置不支援的，按套用時會提示）
DEPTHS = [16, 24, 32]
RATES = [44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000]


# ---------------------------------------------------------------- Windows 音訊裝置
def apo_config_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO") as k:
            return winreg.QueryValueEx(k, "ConfigPath")[0]
    except OSError:
        return r"C:\Program Files\EqualizerAPO\config"


def list_devices():
    """所有輸出裝置：[{guid, name, iface, active, hooked, fmt}]（hooked＝已經裝上 Equalizer APO）"""
    out = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, MM)
    except OSError:
        return out
    with root:
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, guid + r"\Properties") as p:
                    iface = str(winreg.QueryValueEx(p, NAME_KEY)[0])
                    try:
                        desc = str(winreg.QueryValueEx(p, DESC_KEY)[0])
                    except OSError:
                        desc = ""
                    try:
                        fmt = bytes(winreg.QueryValueEx(p, FORMAT_KEY)[0])[8:]
                    except OSError:
                        fmt = b""
                with winreg.OpenKey(root, guid) as k:
                    active = winreg.QueryValueEx(k, "DeviceState")[0] == 1
            except OSError:
                continue
            hooked = False
            try:
                with winreg.OpenKey(root, guid + r"\FxProperties") as fx:
                    j = 0
                    while True:
                        try:
                            val = winreg.EnumValue(fx, j)[1]
                        except OSError:
                            break
                        j += 1
                        hooked = hooked or APO_CLSID in str(val).upper()
            except OSError:
                pass
            out.append({"guid": guid, "name": f"{desc} ({iface})" if desc else iface, "iface": iface, "desc": desc,
                        "active": active, "hooked": hooked, "fmt": fmt})
    return out


def default_device_guid():
    """Windows 目前的預設輸出裝置"""
    try:
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetSpeakers().id.rsplit(".", 1)[-1]
    except Exception:
        devs = [d for d in list_devices() if d["active"]]
        return devs[0]["guid"] if devs else None


def find_device(guid):
    return next((d for d in list_devices() if d["guid"].lower() == (guid or "").lower()), None)


def remove_config(cfg_dir):
    """解除安裝用：拿掉 config.txt 裡調音台的區塊（原本的設定恢復成套用全部裝置），刪掉調音台的設定檔。
    沒有調音台的區塊就什麼都不動。回傳 True＝有改動"""
    path = os.path.join(cfg_dir, "config.txt")
    try:
        text = read_text(path).replace("\r\n", "\n")
    except OSError:
        return False
    if BLOCK_BEGIN not in text or BLOCK_END not in text:
        return False
    rest = text[text.index(BLOCK_END) + len(BLOCK_END):].lstrip("\n")
    lines = rest.split("\n")
    if lines and lines[0].startswith("# 原本的設定（調音台讓它只套用在其他裝置）"):
        lines = lines[2:] if len(lines) > 1 and lines[1].lower().startswith("device:") else lines[1:]
    new_text = text[:text.index(BLOCK_BEGIN)] + "\n".join(lines)
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(new_text)
    try:
        os.remove(os.path.join(cfg_dir, OUT_NAME))
    except OSError:
        pass
    return True


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", "replace")


def ensure_config(cfg_dir, dev, all_guids):
    """config.txt 開頭放一個只給選定裝置的區塊（Include 調音台的設定檔）。
    原本的設定改成只套用在其他裝置（區段寫了這個裝置的代號、名稱或 all 的，把它排除），
    才不會在同一個裝置上疊兩次。第一次改之前會先備份。回傳 True＝有改動"""
    path = os.path.join(cfg_dir, "config.txt")
    text = read_text(path).replace("\r\n", "\n") if os.path.exists(path) else ""
    guid = dev["guid"]
    others = [g for g in all_guids if g.lower() != guid.lower()] or [DUMMY_GUID]
    names = [n.lower() for n in (dev["iface"], dev["desc"], dev["name"]) if n]
    if BLOCK_BEGIN in text and BLOCK_END in text:
        rest = text[text.index(BLOCK_END) + len(BLOCK_END):].lstrip("\r\n")
    else:
        backup = os.path.join(cfg_dir, "config_調音台之前的備份.txt")
        if text and not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(text)
        rest = text
        first = next((ln.strip() for ln in rest.splitlines() if ln.strip() and not ln.strip().startswith("#")), "")
        if first and not first.lower().startswith("device:"):  # 原本沒分裝置的設定＝套用全部 → 改成只套用其他裝置
            rest = "# 原本的設定（調音台讓它只套用在其他裝置）\nDevice: " + "; ".join(others) + "\n" + rest
    lines = []
    for ln in rest.splitlines():
        st = ln.strip()
        if st.lower().startswith("device:"):
            pats = [p.strip() for p in st[7:].split(";") if p.strip()]
            new = []
            for p in pats:
                if p.lower() == "all":
                    new += others
                elif p.lower() == guid.lower() or any(p.lower() in n for n in names):
                    continue
                else:
                    new.append(p)
            if new != pats:
                ln = "Device: " + "; ".join(new or [DUMMY_GUID])
        lines.append(ln)
    block = f"{BLOCK_BEGIN}\nDevice: {guid}\nInclude: {OUT_NAME}\n{BLOCK_END}\n"
    new_text = block + "\n".join(lines) + ("\n" if lines else "")
    if new_text == text:
        return False
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(new_text)
    return True


def parse_fmt(fmt):
    """WAVEFORMATEX(TENSIBLE) → (有效位元, 取樣率, 容器位元)"""
    if len(fmt) < 16:
        return None
    container = int.from_bytes(fmt[14:16], "little")
    bits = container
    if fmt[0:2] == b"\xfe\xff" and len(fmt) >= 20:
        bits = int.from_bytes(fmt[18:20], "little") or container
    return bits, int.from_bytes(fmt[4:8], "little"), container


def set_device_format(guid, bits, rate):
    """用 Windows 音效設定同一套介面（IPolicyConfig）改輸出格式，不需要系統管理員"""
    import comtypes
    from comtypes import COMMETHOD, GUID, IUnknown

    class IPolicyConfig(IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [
            COMMETHOD([], ctypes.HRESULT, "GetMixFormat", (["in"], ctypes.c_wchar_p),
                      (["out"], ctypes.POINTER(ctypes.c_void_p))),
            COMMETHOD([], ctypes.HRESULT, "GetDeviceFormat", (["in"], ctypes.c_wchar_p), (["in"], ctypes.c_int),
                      (["out"], ctypes.POINTER(ctypes.c_void_p))),
            COMMETHOD([], ctypes.HRESULT, "ResetDeviceFormat", (["in"], ctypes.c_wchar_p)),
            COMMETHOD([], ctypes.HRESULT, "SetDeviceFormat", (["in"], ctypes.c_wchar_p),
                      (["in"], ctypes.c_void_p), (["in"], ctypes.c_void_p)),
        ]

    policy = comtypes.CoCreateInstance(GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"),
                                       IPolicyConfig, comtypes.CLSCTX_ALL)
    pcm = uuid.UUID("00000001-0000-0010-8000-00aa00389b71").bytes_le
    error = None
    for container in ((16,) if bits == 16 else (32, 24) if bits == 24 else (32,)):
        block = 2 * container // 8
        buf = ctypes.create_string_buffer(struct.pack("<HHIIHHHHI16s", 0xFFFE, 2, rate, rate * block, block,
                                                      container, 22, bits, 3, pcm))
        try:
            ptr = ctypes.cast(buf, ctypes.c_void_p)
            policy.SetDeviceFormat("{0.0.0.00000000}." + guid, ptr, ptr)
            return
        except Exception as e:  # 這種容器不行就換下一種
            error = e
    raise error


BROWSERS = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave", "opera.exe": "Opera"}


def other_player(guid):
    """Tidal 以外正在出聲的程式（YouTube Music、瀏覽器…）。EQ 是整個裝置都套用，這裡只是顯示用；
    系統預設輸出不是調音台選的裝置時不顯示（那時聲音不會經過 EQ）"""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        if not guid or not AudioUtilities.GetSpeakers().id.lower().endswith(guid.lower()):
            return None
        for sess in AudioUtilities.GetAllSessions():
            name = sess.Process.name() if sess.Process else ""
            if (name and not name.lower().startswith("tidal") and sess.State == 1
                    and sess._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue() > 0.0005):
                return name
    except Exception:
        pass
    return None


def youtube_window():
    """有標題含 YouTube 的視窗（瀏覽器目前分頁或 YouTube Music 程式）→ 回傳 "YouTube Music" / "YouTube"""
    found = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _l):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "YouTube" in buf.value:
                found.append(buf.value)
        return True
    user32.EnumWindows(cb, 0)
    return ("YouTube Music" if any("YouTube Music" in t for t in found) else "YouTube") if found else None


def read_tidal_status():
    """從 Tidal 的 player.log 讀出目前歌曲的音質、送出格式、播放狀態、實時位元率"""
    path = os.path.join(os.environ.get("APPDATA", ""), "TIDAL", "Logs", "player.log")
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 300_000))
            text = fh.read().decode("utf-8", "ignore")
    except OSError:
        return {}
    info = {}
    src = re.findall(r"Decoder got\s+\d+\s+total frames for\s+AudioMetadata \[ channels: (\d+) "
                     r"bitsPerSample: (\d+) sampleRate: (\d+)", text)
    if src:
        info["src"] = tuple(int(x) for x in src[-1])
    outs = re.findall(r"\] -\s+\[WAVEFORMATEXTENSIBLE Format:[^\n]*", text)
    if outs:
        rate = re.search(r"nSamplesPerSec: (\d+)", outs[-1])
        bits = re.search(r"wValidBitsPerSample: (\d+)", outs[-1]) or re.search(r"wBitsPerSample: (\d+)", outs[-1])
        if rate and bits:
            info["out"] = (int(bits.group(1)), int(rate.group(1)))
    state = re.findall(r'"signal": "media\.state", "state": "(\w+)"', text)
    if state:
        info["state"] = state[-1]
    mode = re.findall(r"Mode \[\s*(\w+)\s*\]", text)
    if mode:
        info["mode"] = mode[-1]
    # 位元率：Tidal 開頭先連抓幾段存著，之後每播完一段（1 MB）才抓下一段，
    # 所以「兩次抓取的間隔」＝播完這段花的時間 → 換算成正在播放那段的實際位元率
    start = text.rfind("BufferStream::setSize:")
    if start < 0:
        return info
    seg = text[start:]
    size = int(re.match(r"BufferStream::setSize:\s*(\d+)", seg).group(1))
    dur = re.search(r'"duration": ([\d.]+)', seg)
    if dur and float(dur.group(1)) > 0:
        info["avg_kbps"] = size * 8 / float(dur.group(1)) / 1000
    reqs = [(datetime.strptime(ts, "%a %b %d %Y %H:%M:%S"), int(a), int(b)) for ts, a, b in re.findall(
        r"\((\w{3} \w{3} \d+ \d{4} [\d:]+)\) \[\w+\] -\s+Range: \[\s*(\d+)\s*,\s*(\d+)\s*\]", seg)]
    if reqs and reqs[-1][2] + 1 >= size:
        info["done"] = True  # 整首都下載完了，後面不會再有新數據
    steady = [(b1 - a1 + 1, (t2 - t1).total_seconds())
              for (t1, a1, b1), (t2, _a, _b) in zip(reqs, reqs[1:]) if (t2 - t1).total_seconds() >= 3]
    if steady:
        last = steady[-2:]  # 最近兩段平均，抵銷紀錄時間只到秒的誤差
        gap = (datetime.now() - reqs[-1][0]).total_seconds()
        if gap < 3 * last[-1][1] or info.get("done"):
            info["rt_kbps"] = sum(n for n, _ in last) * 8 / sum(s for _, s in last) / 1000
    return info


def fmt_rate(rate):
    return f"{rate / 1000:g} kHz"


# ---------------------------------------------------------------- EQ 計算
def filter_db(kind, fc, gain, q, f, fs=48000.0):
    """單一濾波器在頻率 f 的增益（dB），跟 Equalizer APO 用的公式一樣"""
    if not gain:
        return 0.0
    A = 10 ** (gain / 40)
    w0 = 2 * math.pi * fc / fs
    c, al = math.cos(w0), math.sin(w0) / (2 * q)
    if kind == "PK":
        b = (1 + al * A, -2 * c, 1 - al * A)
        a = (1 + al / A, -2 * c, 1 - al / A)
    else:
        sq = 2 * math.sqrt(A) * al
        if kind == "LSC":
            b = (A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c),
                 A * ((A + 1) - (A - 1) * c - sq))
            a = ((A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c),
                 (A + 1) + (A - 1) * c - sq)
        else:  # HSC
            b = (A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c),
                 A * ((A + 1) + (A - 1) * c - sq))
            a = ((A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c),
                 (A + 1) - (A - 1) * c - sq)
    z = cmath.exp(-2j * math.pi * f / fs)
    h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return 20 * math.log10(abs(h))


def curve(filters):
    return [sum(filter_db(*fl, f) for fl in filters) for f in FREQS]


def update_headroom():
    """固定預留＝目前耳機的每一種校正 × 每個內建風格裡，最大的加強（取 0.5 dB，6–18 dB 之間）"""
    global HEADROOM
    bases = [curve(fl) for _n, fl in BASES.values()]
    cache, worst = {}, 0.0
    for _n, vals, width, _cf, _src in STYLES:
        key = tuple(vals)
        if key not in cache:
            cache[key] = curve([(k, f, g, q) for (_b, k, f, q, _h), g in zip(BANDS, vals) if g])
        wk = 20 * math.log10(1 + width / 100)
        worst = max(worst, max(max(a + b for a, b in zip(bc, cache[key])) for bc in bases) + wk)
    HEADROOM = min(18.0, max(6.0, math.ceil(worst * 2) / 2))
    return HEADROOM


# ISO 226:2003 等響曲線（用來補償「比平常大聲／小聲」時耳朵聽到的低音、高音變化）
_ISO_F = [20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000,
          2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500]
_ISO_A = [.532, .506, .480, .455, .432, .409, .387, .367, .349, .330, .315, .301, .288, .276, .267, .259, .253, .250,
          .246, .244, .243, .243, .243, .242, .242, .245, .254, .271, .301]
_ISO_L = [-31.6, -27.2, -23.0, -19.1, -15.9, -13.0, -10.3, -8.1, -6.2, -4.5, -3.1, -2.0, -1.1, -0.4, 0.0, 0.3, 0.5,
          0.0, -2.7, -4.1, -1.0, 1.7, 2.5, 1.2, -2.1, -7.1, -11.2, -10.7, -3.1]
_ISO_T = [78.5, 68.7, 59.5, 51.1, 44.0, 37.5, 31.5, 26.5, 22.1, 17.9, 14.4, 11.4, 8.6, 6.2, 4.4, 3.0, 2.2, 2.4, 3.5,
          1.7, -1.3, -4.2, -6.0, -5.4, -1.5, 6.0, 12.6, 13.9, 12.3]


def _iso226(phon):
    return [10 / a * math.log10(4.47e-3 * (10 ** (0.025 * phon) - 1.15) + (0.4 * 10 ** ((t + l) / 10 - 9)) ** a) - l + 94
            for a, l, t in zip(_ISO_A, _ISO_L, _ISO_T)]


def equal_loudness(actual, intended=80.0):
    """在 actual phon 聽、想聽到 intended phon 的平衡，各頻率要補多少（dB，500 Hz–2 kHz 當 0）"""
    import numpy as np
    d = np.array(_iso226(actual)) - actual - (np.array(_iso226(intended)) - intended)
    d = np.interp(np.log(FREQS), np.log(_ISO_F), d)
    f = np.array(FREQS)
    return d - d[(f >= 500) & (f <= 2000)].mean()


def fit_bands(target, cap_bass=6.0):
    """把目標曲線擬合到五個細調滑桿（高斯-牛頓，10 kHz 以上權重低），取 0.5 dB"""
    import numpy as np
    f = np.array(FREQS)
    w = np.sqrt(np.where(f <= 10000, 1.0, 0.3))
    model = lambda x: np.array(curve([(k, fc, g, q) for (_n, k, fc, q, _h), g in zip(BANDS, x)]))
    x = np.zeros(len(BANDS))
    for _ in range(10):
        r = model(x) - target
        J = np.zeros((len(f), len(BANDS)))
        for i in range(len(BANDS)):
            e = np.zeros(len(BANDS))
            e[i] = 0.1
            J[:, i] = (model(x + e) - model(x)) / 0.1
        x = np.clip(x + np.linalg.lstsq(J * w[:, None], -r * w, rcond=None)[0], -6, 6)
    x = np.round(x * 2) / 2
    x[0] = min(x[0], cap_bass)  # 低音最多 +6 dB（Olive 2022 愛低音族群偏好的上限）
    return [float(v) + 0.0 for v in x]


def tidal_tracks():
    """讀 Tidal 在這台電腦的快取（收藏、播放清單的清單頁）：[(歌名, 歌手們, ReplayGain, 峰值, 音質)]"""
    import gzip
    try:
        import brotli
    except ImportError:
        brotli = None
    cache = os.path.join(os.environ.get("APPDATA", ""), "TIDAL", "Cache", "Cache_Data")
    tracks = {}
    try:
        names = os.listdir(cache)
    except OSError:
        return []
    for fn in names:
        path = os.path.join(cache, fn)
        try:
            if not fn.startswith("f_") or os.path.getsize(path) > 3_000_000:
                continue
            with open(path, "rb") as fh:
                head = fh.read(2)
                plain_or_gzip = head in (b'{"', b"\x1f\x8b")
                if not plain_or_gzip and (not brotli or head in (b"\xff\xd8", b"\x89P", b"wO", b"RI", b"GI", b"\x00\x00")):
                    continue
                raw = head + fh.read()
        except OSError:
            continue
        data = None
        for dec in (lambda b: b, gzip.decompress, brotli.decompress if brotli else None):
            if dec is None:
                continue
            try:
                data = json.loads(dec(raw))
                break
            except Exception:
                pass
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            continue
        for it in data["items"]:
            t = it.get("item", it) if isinstance(it, dict) else None
            if isinstance(t, dict) and "duration" in t and ("artists" in t or "artist" in t) and "id" in t:
                arts = [a.get("name", "") for a in (t.get("artists") or [t.get("artist") or {}])]
                tracks[t["id"]] = (t.get("title", ""), arts, t.get("replayGain"), t.get("peak"), t.get("audioQuality"))
    return list(tracks.values())


def tidal_normalization():
    """Tidal 的「音量標準化」設定（從它的本機設定讀）：'NONE'＝關閉；讀不到回傳 None"""
    base = os.path.join(os.environ.get("APPDATA", ""), "TIDAL")
    files = []
    for sub in (("IndexedDB", "https_desktop.tidal.com_0.indexeddb.leveldb"), ("Local Storage", "leveldb")):
        folder = os.path.join(base, *sub)
        try:
            files += [os.path.join(folder, fn) for fn in os.listdir(folder)]
        except OSError:
            pass
    found = None
    for path in sorted(files, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0):
        try:
            with open(path, "rb") as fh:
                for m in re.finditer(rb'Normalization"[\x00-\x20]([A-Z_]+)', fh.read()):
                    found = m.group(1).decode()
        except OSError:
            pass
    return found


def analyze_tidal():
    """依這台電腦的 Tidal 收藏產生「你的歌單」：響度、峰值、音質特別極端的歌各給一個設定。
    回傳 (風格清單, 白話介紹)；沒有 Tidal 或歌太少就回傳空的"""
    import collections
    import statistics
    try:
        tracks = tidal_tracks()
    except Exception:
        return [], {}
    rg = [t[2] for t in tracks if t[2] is not None]
    if len(rg) < 50:
        return [], {}
    med = statistics.median(rg)
    loud_ok = tidal_normalization() == "NONE"  # 標準化開著時 Tidal 會自己把音量拉平，就不用補響度

    def who(group):
        top = collections.Counter(a for t in group for a in t[1] if a and len(a) <= 18).most_common(3)
        return "、".join(a for a, _n in top)

    mine, plain = [], {}
    if loud_ok:
        g = [t for t in tracks if t[2] is not None and t[2] <= med - 3]
        if len(g) >= 10:
            gap = med - statistics.median(t[2] for t in g)
            mine.append(("超大聲的歌", fit_bands(equal_loudness(80 + gap)), 0, 0,
                         f"你收藏裡 {len(g)} 首比中位數大聲 {gap:.1f} dB（Tidal 音量標準化關閉）→ ISO 226 反向等響補償"))
            plain["超大聲的歌"] = f"{who(g)} 這類壓很滿的歌：比你其他歌大聲約 {gap:.0f} dB，低音收一點，不轟、不累"
        g = [t for t in tracks if t[2] is not None and t[2] >= med + 7.5]
        if len(g) >= 10:
            gap = statistics.median(t[2] for t in g) - med
            mine.append(("超小聲的歌", fit_bands(equal_loudness(80 - gap)), 0, 0,
                         f"你收藏裡 {len(g)} 首比中位數小聲 {gap:.1f} dB → ISO 226 等響補償"))
            plain["超小聲的歌"] = f"{who(g)} 這類：比你其他歌小聲約 {gap:.0f} dB，補回小聲時聽不到的低音和高音"
    g = [t for t in tracks if (t[3] or 0) >= 0.999]
    if len(g) >= 10:
        mine.append(("容易爆音的歌", [0, 0, 0, -2, 0], 0, 0,
                     f"你收藏裡 {len(g)} 首峰值頂到滿格；原檔的破音比音樂小 40–60 dB，依 ISO 226 在 2–4 kHz 最容易被聽到 → 臨場感 −2 dB"))
        plain["容易爆音的歌"] = f"{who(g)} 這類音量頂到滿的歌：破音的刺耳感少一點，播放時也不會再多爆"
    g = [t for t in tracks if t[4] in ("HIGH", "LOW")]
    if len(g) >= 5:
        mine.append(("有損音質的歌", [0, 0, 0, 0, -3], 0, 0,
                     f"你收藏裡 {len(g)} 首是有損壓縮（上傳檔或舊版），壓縮雜訊集中在高頻 → 高頻 −3 dB（保守值）"))
        plain["有損音質的歌"] = f"{who(g) or '上傳的歌'} 這類有損壓縮的歌：高頻收一點，壓縮雜音比較不刺耳"
    return mine, plain


def build_config(filters, width=0, crossfeed=0, balance=0.0, reverb_file="", room_db=None, extra=0.0):
    """產生設定檔內容，回傳 (內容, 最高加強 dB)。音量固定降 HEADROOM，EQ 關閉時也一樣。
    width＝聲場加寬百分比、crossfeed＝交叉饋送等級、balance＝左右平衡（正＝偏右）"""
    k = width / 100
    eq = curve(filters) if filters else [0.0] * len(FREQS)
    if room_db:  # 殘響的最壞增益疊上去
        eq = [a + b for a, b in zip(eq, room_db)]
    peak = max(eq) + 20 * math.log10(1 + k)
    lines = ["# written by headphone tuner", f"Preamp: {-(HEADROOM + extra):.1f} dB"]
    lines += [f"Filter: ON {t} Fc {fc:g} Hz Gain {g:.1f} dB Q {q:.2f}" for t, fc, g, q in filters]
    if crossfeed:  # 轉成中(M)/側(S) → 只把低頻的側訊號變小 → 低頻互相滲一點過去，像聽喇叭
        _name, gain, fc = CROSSFEED[crossfeed]
        lines += ["Copy: L=0.5*L+0.5*R R=0.5*L+-0.5*R", "Channel: R",
                  f"Filter: ON LSC Fc {fc} Hz Gain {gain:.1f} dB Q 0.50",
                  "Channel: all", "Copy: L=L+R R=L+-1*R"]  # 注意：一定要寫 -1*R，寫 -R 會變成直流訊號
    if k:  # 左右聲道差異放大 → 聲場變寬
        lines.append(f"Copy: L={1 + k:.2f}*L+{-k:.2f}*R R={1 + k:.2f}*R+{-k:.2f}*L")
    if balance:  # 只壓低另一邊，不會多加音量
        side = "L" if balance > 0 else "R"
        lines.append(f"Copy: {side}={10 ** (-abs(balance) / 20):.4f}*{side}")
    if reverb_file:  # 殘響：直達聲＋空間反射（檔案依 DAC 取樣率做）
        lines.append(f"Convolution: {reverb_file}")
    return "\n".join(lines) + "\n", peak


def start_hotkeys(root, actions, on_fail):
    """註冊全域快捷鍵（視窗縮小、在 Tidal 裡也能用）。actions: {id: 函式}"""
    q = queue.Queue()

    def loop():
        user32 = ctypes.windll.user32
        for hid, mods, vk, name, _desc in HOTKEYS:
            if not user32.RegisterHotKey(None, hid, mods | 0x4000, vk):  # 0x4000＝按住不連發
                q.put(("fail", name))
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                q.put(("key", msg.wParam))

    def poll():
        while not q.empty():
            kind, val = q.get()
            if kind == "key" and val in actions:
                actions[val]()
            elif kind == "fail":
                on_fail(val)
        root.after(100, poll)

    threading.Thread(target=loop, daemon=True).start()
    poll()


def pick_fonts(root):
    """挑電腦上有的最好看字體：中文 Noto Sans TC（標題用 Medium）、數字 Inter"""
    global FONT, FONT_MED, NUM
    fams = set(tkfont.families(root))
    if "Noto Sans TC" in fams:
        FONT = "Noto Sans TC"
        FONT_MED = "Noto Sans TC Medium" if "Noto Sans TC Medium" in fams else FONT
    NUM = next((f for f in ("Inter SemiBold", "Inter", "Segoe UI Variable Text Semibold", "Segoe UI")
                if f in fams), FONT)


def load_headphone_index():
    """AutoEQ 的耳機清單（30 天內下載過就用快取）→ ({型號: [(來源, 路徑)]}, 錯誤訊息)"""
    import time
    path = os.path.join(HP_DIR, "INDEX.md")
    try:
        if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 30 * 86400:
            os.makedirs(HP_DIR, exist_ok=True)
            with urllib.request.urlopen(AUTOEQ_RAW + "INDEX.md", timeout=30) as r:
                data = r.read()
            with open(path, "wb") as fh:
                fh.write(data)
        text = open(path, encoding="utf-8").read()
    except Exception as e:
        return {}, str(e)
    models = {}
    for m in re.finditer(r"^- \[(.+)\]\((\./.+)\) by (.+)$", text, re.M):
        name, link, by = m.groups()
        models.setdefault(name, []).append((by.split(" on ")[0].strip(), link[2:]))
    return models, None


def download_headphone(name, entries):
    """下載這支耳機最多 3 個不同來源的校正（依可信度排序）→ ([[來源, 濾波器]], 錯誤訊息)"""
    rank = lambda src: SOURCE_ORDER.index(src) if src in SOURCE_ORDER else len(SOURCE_ORDER)
    seen, out, err = set(), [], None
    for src, link in sorted(entries, key=lambda e: rank(e[0])):
        if src in seen or len(out) >= 3:
            continue
        leaf = urllib.parse.unquote(link.rsplit("/", 1)[-1])
        url = AUTOEQ_RAW + link + "/" + urllib.parse.quote(leaf + " ParametricEQ.txt")
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
        except Exception as e:
            err = str(e)
            continue
        fl = [[t, float(f), float(g), float(q)] for t, f, g, q in
              re.findall(r"ON (LSC|HSC|PK) Fc ([\d.]+) Hz Gain ([-\d.]+) dB Q ([\d.]+)", text)]
        if fl:
            seen.add(src)
            out.append([src, fl])
    return out, (None if out else err)


def make_shortcut(folder=None):
    """在桌面（或指定資料夾）建立「耳機調音台」捷徑，回傳捷徑路徑"""
    import comtypes.client
    shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
    folder = folder or shell.SpecialFolders("Desktop")
    path = os.path.join(folder, "耳機調音台.lnk")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    lnk = shell.CreateShortcut(path)
    lnk.TargetPath = pyw if os.path.exists(pyw) else sys.executable
    lnk.Arguments = f'"{os.path.abspath(__file__)}"'
    lnk.WorkingDirectory = APP_DIR
    if os.path.exists(ICON_PATH):
        lnk.IconLocation = ICON_PATH
    lnk.Save()
    return path


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- 自製元件
class Pill(tk.Label):
    """扁平按鈕：滑過變亮；選中或主要按鈕是藍底白字"""

    def __init__(self, master, app, text, command, primary=False, size=10, font=None):
        super().__init__(master, text=text, font=(font or FONT, size), cursor="hand2",
                         padx=app.px(12), pady=app.px(4))
        self.command, self.primary, self.selected, self.hover = command, primary, False, False
        self.bind("<Enter>", lambda _e: self.paint(hover=True))
        self.bind("<Leave>", lambda _e: self.paint(hover=False))
        self.bind("<Button-1>", lambda _e: self.command())
        self.paint()

    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.paint()

    def paint(self, hover=None):
        if hover is not None:
            self.hover = hover
        if self.primary or self.selected:
            self.config(bg=ACCENT_HI if self.hover else ACCENT, fg="white")
        else:
            self.config(bg=PILL_HOVER if self.hover else PILL, fg=TEXT)


class Slider(tk.Canvas):
    """滑桿：圓角軌道、從 0 往外填藍色、白色圓把手；可拖曳、點擊、滾輪，雙擊歸零"""

    def __init__(self, master, app, var, lo, hi, step, length, on_change):
        super().__init__(master, width=app.px(length), height=app.px(26), bg=master["bg"],
                         highlightthickness=0, cursor="hand2")
        self.app, self.var, self.lo, self.hi, self.step, self.on_change = app, var, lo, hi, step, on_change
        self.r = app.px(8)
        self.bind("<Button-1>", self.drag)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<MouseWheel>", lambda e: self.set(self.var.get() + (step if e.delta > 0 else -step)))
        self.bind("<Double-Button-1>", lambda _e: self.set(min(max(0, lo), hi)))
        self.bind("<Configure>", lambda _e: self.draw())
        var.trace_add("write", lambda *_: self.draw())

    def set(self, v):
        v = min(self.hi, max(self.lo, round(v / self.step) * self.step))
        if v != self.var.get():
            self.var.set(v)
            self.on_change()

    def pos(self, v):
        pad = self.r + 2
        return pad + (self.winfo_width() - 2 * pad) * (v - self.lo) / (self.hi - self.lo)

    def drag(self, e):
        pad = self.r + 2
        self.set(self.lo + (e.x - pad) / max(1, self.winfo_width() - 2 * pad) * (self.hi - self.lo))

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        cy, t, pad = h / 2, self.app.px(5), self.r + 2
        self.create_line(pad, cy, w - pad, cy, width=t, fill=TRACK, capstyle="round")
        zero, x = self.pos(min(max(0, self.lo), self.hi)), self.pos(self.var.get())
        if self.lo < 0 < self.hi:
            self.create_line(zero, cy - self.app.px(7), zero, cy + self.app.px(7), fill=SUB)
        if abs(x - zero) > 1:
            self.create_line(zero, cy, x, cy, width=t, fill=ACCENT, capstyle="round")
        self.create_oval(x - self.r, cy - self.r, x + self.r, cy + self.r, fill="white",
                         outline=ACCENT, width=self.app.px(2))


class Toggle(tk.Canvas):
    """開關：藍色＝開"""

    def __init__(self, master, app, var, command):
        self.w, self.h = app.px(42), app.px(24)
        super().__init__(master, width=self.w, height=self.h, bg=master["bg"], highlightthickness=0,
                         cursor="hand2")
        self.app, self.var, self.command = app, var, command
        self.bind("<Button-1>", self.click)
        var.trace_add("write", lambda *_: self.draw())
        self.draw()

    def click(self, _e):
        self.var.set(not self.var.get())
        self.command()

    def draw(self):
        self.delete("all")
        w, h = self.w - 1, self.h - 1
        on = bool(self.var.get())
        c = ACCENT if on else TRACK
        self.create_oval(0, 0, h, h, fill=c, outline=c)
        self.create_oval(w - h, 0, w, h, fill=c, outline=c)
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=c, outline=c)
        k, x = self.app.px(3), (w - h if on else 0)
        self.create_oval(x + k, k, x + h - k, h - k, fill="white", outline="white" if on else KNOB_EDGE)


# ---------------------------------------------------------------- 主視窗
class App:
    def __init__(self, root):
        self.root = root
        self.scale = root.winfo_fpixels("1i") / 96
        self.cfg_dir = CONFIG_DIR or apo_config_dir()
        s = load_settings()
        last = s.get("last", {})
        self.presets = s.get("presets", {})
        self.hp = s.get("headphone")  # {"name", "sources": [[來源, 濾波器], ...]}
        set_headphone(self.hp)
        update_headroom()
        self.dev_guid = s.get("device") or default_device_guid()
        self._perm_asked = False
        self.enabled = tk.BooleanVar(value=last.get("enabled", True))
        self.base = tk.StringVar(value=last.get("base") if last.get("base") in BASES else default_base())
        self.bands = [tk.DoubleVar(value=v) for v in (last.get("bands") or [0] * len(BANDS))]
        self.width = tk.DoubleVar(value=last.get("width", 0))
        self.passthrough = tk.BooleanVar(value=last.get("passthrough", False))
        self.crossfeed = tk.DoubleVar(value=last.get("crossfeed", 0))
        self.balance = tk.DoubleVar(value=last.get("balance", 0))
        self.room = tk.DoubleVar(value=last.get("room", 0))
        self.cur_fmt = self.pend_fmt = None  # DAC 目前的格式／準備要套用的格式 (位元, 取樣率)
        self._job = self._auto_job = self._toast = None
        self.group = 0  # 快速風格目前顯示哪個分頁
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        pick_fonts(root)
        self.style_theme()
        self.build()
        root.update_idletasks()
        self.fit_style_grid()
        self.fit_source_box()
        self.changed()
        self.tick()
        start_hotkeys(root, {1: self.hotkey_toggle_eq, 2: lambda: self.hotkey_style(1),
                             3: lambda: self.hotkey_style(-1)}, self.hotkey_failed)
        # 版面排好後把視窗大小固定住：之後文字變長變短都不會讓視窗跳動
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        x = max(0, (root.winfo_screenwidth() - w) // 2)  # 開在螢幕正中間，下面才不會跑出螢幕
        y = max(0, (root.winfo_screenheight() - h) // 2 - self.px(24))
        root.geometry(f"{w}x{h}+{x}+{y}")
        # 視窗內快捷鍵：空白鍵開關 EQ、←→ 換風格、數字鍵換分頁
        root.bind("<space>", lambda _e: self.hotkey_toggle_eq())
        root.bind("<Right>", lambda _e: self.hotkey_style(1))
        root.bind("<Left>", lambda _e: self.hotkey_style(-1))
        for k in range(len(STYLE_GROUPS)):
            root.bind(str(k + 1), lambda _e, g=k: self.show_group(g))
        root.focus_set()
        root.after(400, self.first_run)

    def first_run(self):
        """第一次打開：檢查 Equalizer APO、整理 config.txt、還沒選耳機就先選"""
        if not os.path.isdir(self.cfg_dir):
            if messagebox.askyesno("還沒安裝等化器核心",
                                   "這台電腦還沒安裝 Equalizer APO（調音台靠它處理聲音）。\n\n"
                                   "要打開下載頁面嗎？安裝時在設定程式勾選你的耳機用的輸出裝置，裝完重新開機。",
                                   parent=self.root):
                os.startfile(APO_URL)
            return
        self.setup_config()
        if not self.hp:
            self.choose_headphone()

    def setup_config(self):
        dev = find_device(self.dev_guid)
        if not dev:
            return
        try:
            if ensure_config(self.cfg_dir, dev, [d["guid"] for d in list_devices()]):
                self.toast(f"已設定：{dev['name']}")
            self.changed()
        except PermissionError:
            self.fix_permission()
        except OSError as e:
            self.status.config(text=f"✗ 設定檔寫不進去：{e}", fg=ORANGE)

    def fix_permission(self):
        """Equalizer APO 的設定資料夾預設只有系統管理員能寫：請使用者同意一次，之後就不用了"""
        if self._perm_asked:
            return
        self._perm_asked = True
        if not messagebox.askokcancel("需要一次權限",
                                      "調音台要寫入 Equalizer APO 的設定資料夾，\n需要系統管理員同意一次（之後就不用了）。",
                                      parent=self.root):
            return
        args = f'"{self.cfg_dir}" /grant *S-1-5-32-545:(OI)(CI)M /T /Q'  # 讓「使用者」群組可以修改（不分語言版本）
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", "icacls", args, None, 0) > 32:
            self.root.after(2500, self.setup_config)

    def px(self, v):
        return int(v * self.scale)

    # ---------- 畫面 ----------
    def style_theme(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("Dark.TCombobox", fieldbackground=PILL, background=PILL, foreground=TEXT,
                     arrowcolor=TEXT, bordercolor=LINE, lightcolor=PILL, darkcolor=PILL,
                     selectbackground=PILL, selectforeground=TEXT, padding=self.px(4))
        st.map("Dark.TCombobox", fieldbackground=[("readonly", PILL)], foreground=[("readonly", TEXT)],
               selectbackground=[("readonly", PILL)], selectforeground=[("readonly", TEXT)])
        for k, v in (("background", PILL), ("foreground", TEXT), ("selectBackground", ACCENT),
                     ("selectForeground", "white"), ("font", (FONT, 10))):
            self.root.option_add(f"*TCombobox*Listbox.{k}", v)

    def label(self, parent, text="", size=10, color=TEXT, bold=False, font=None, **kw):
        if font:
            f = (font, size)
        elif bold:  # 有 Medium 字重就用 Medium，比粗體精緻
            f = (FONT_MED, size) if FONT_MED != FONT else (FONT, size, "bold")
        else:
            f = (FONT, size)
        return tk.Label(parent, text=text, font=f, fg=color, bg=parent["bg"], **kw)

    def card(self, parent, title, hint=None):
        px = self.px
        outer = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE)
        outer.pack(fill="x", pady=(0, px(8)))
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=px(14), pady=px(8))
        top = tk.Frame(inner, bg=PANEL)
        top.pack(fill="x", pady=(0, px(6)))
        tk.Frame(top, bg=ACCENT, width=px(3), height=px(15)).pack(side="left", padx=(0, px(8)))
        self.label(top, title, 11, bold=True).pack(side="left")
        if hint:
            self.label(top, hint, 9, SUB).pack(side="left", padx=px(8))
        return inner

    def chip(self, parent):
        return tk.Label(parent, font=(FONT, 10), bg=PILL, fg=TEXT, pady=self.px(3))

    def build(self):
        px, r = self.px, self.root
        r.title("耳機調音台")
        r.configure(bg=BG)

        # 頂部：標題＋裝置狀態
        head = tk.Frame(r, bg=HEADER)
        head.pack(fill="x")
        tk.Frame(r, bg=LINE, height=1).pack(fill="x")
        self.label(head, "耳機調音台", 16, bold=True).pack(side="left", padx=(px(18), px(10)), pady=px(8))
        self.hp_btn = Pill(head, self, "", self.choose_headphone, size=9)
        self.hp_btn.pack(side="left", padx=(0, px(6)))
        self.devsel_btn = Pill(head, self, "", self.choose_device, size=9)
        self.devsel_btn.pack(side="left")
        self.paint_header()
        self.dev_chip = tk.Label(head, font=(FONT, 10, "bold"), padx=px(12), pady=px(4))
        self.dev_chip.pack(side="right", padx=px(18))
        self.fix_btn = Pill(head, self, "點我接上", self.open_selector, primary=True)

        # 播放資訊列
        bar = tk.Frame(r, bg=BG)
        bar.pack(fill="x", padx=px(14), pady=(px(10), 0))
        self.chips = {k: self.chip(bar) for k in ("state", "src", "kind", "rate", "arrow", "dac", "mode")}
        for k, c in self.chips.items():
            c.pack(side="left", padx=(0, px(6)))
        self.chips["arrow"].config(bg=BG, fg=SUB)

        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True, padx=px(14), pady=(px(10), 0))
        cols = [tk.Frame(body, bg=BG) for _ in range(3)]
        for i, col in enumerate(cols):
            col.pack(side="left", fill="y", anchor="n", padx=(0 if i == 0 else px(10), 0))
        left, mid, right = cols

        # 左：基本設定
        c = self.card(left, "基本設定")
        self.toggle_row(c, "開啟 EQ", "關掉＝原音比較，音量不變", self.enabled, self.changed)
        self.toggle_row(c, "直通模式", "類似獨佔：完全不處理聲音", self.passthrough, self.toggle_passthrough)
        self.label(c, "耳機校正（AutoEQ 量測，目標 Harman 2018）", 8, SUB).pack(anchor="w", pady=(px(8), px(2)))
        grid = tk.Frame(c, bg=PANEL)
        grid.pack(fill="x")
        self.base_grid = grid
        self.build_base_pills()
        grid.columnconfigure((0, 1), weight=1, uniform="b")

        # 左：快速風格
        c = self.card(left, "快速風格", "滑過看介紹　←→ 換風格　空白鍵 A/B")
        tabs = tk.Frame(c, bg=PANEL)
        tabs.pack(fill="x")
        self.tabs = []
        for gi, (gname, _g) in enumerate(STYLE_GROUPS):
            t = tk.Frame(tabs, bg=PANEL)
            t.pack(side="left", padx=(0, px(12)))
            lbl = self.label(t, gname, 10, bold=True, cursor="hand2")
            lbl.pack()
            bar = tk.Frame(t, bg=PANEL, height=px(3))
            bar.pack(fill="x", pady=(px(2), 0))
            lbl.bind("<Button-1>", lambda _e, i=gi: self.show_group(i))
            self.tabs.append((lbl, bar))
        tk.Frame(c, bg=LINE, height=1).pack(fill="x", pady=(0, px(6)))
        self.style_grid = tk.Frame(c, bg=PANEL)
        self.style_grid.pack(fill="x")
        self.style_btns = {}  # STYLES 的索引 → 按鈕（只有目前分頁的）
        # 依據說明放在固定大小的框裡，文字長短不會撐動版面（大小在 fit_source_box 算）
        self.src_box = tk.Frame(c, bg=PILL, height=1)
        self.src_box.pack(fill="x", pady=(px(8), 0))
        self.src_box.pack_propagate(False)
        self.style_name = self.label(self.src_box, "", 11, ACCENT, bold=True, justify="left", anchor="nw")
        self.style_name.pack(fill="x", padx=px(10), pady=(px(6), 0))
        self.style_plain = self.label(self.src_box, "", 10, TEXT, justify="left", anchor="nw")
        self.style_plain.pack(fill="x", padx=px(10), pady=(0, px(6)))
        self.show_group(0)

        # 中：曲線
        c = self.card(mid, "EQ 曲線", "藍＝整體效果　橘虛線＝你的細調")
        self.cw, self.ch = px(500), px(190)
        self.canvas = tk.Canvas(c, width=self.cw, height=self.ch, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="x")

        # 中：細調
        c = self.card(mid, "細調", "拖曳、滾輪都可以；雙擊歸零")
        g = tk.Frame(c, bg=PANEL)
        g.pack(fill="x")
        self.val_lbls = [self.slider_row(g, i, name, hint, var, -6, 6, 0.5, 300)
                         for i, ((name, _k, _f, _q, hint), var) in enumerate(zip(BANDS, self.bands))]
        g.columnconfigure(1, weight=1)
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x", pady=(px(8), 0))
        Pill(row, self, "↺ 恢復預設（推薦校正、全部歸零）", self.reset_default).pack(side="right")
        Pill(row, self, "細調歸零", lambda: self.set_bands([0] * len(BANDS), 0)).pack(side="right", padx=px(6))

        # 右：空間感與平衡
        c = self.card(right, "空間感與平衡")
        g = tk.Frame(c, bg=PANEL)
        g.pack(fill="x")
        self.width_lbl = self.slider_row(g, 0, "聲場寬度", "左右拉開", self.width, 0, 40, 5, 180)
        self.cf_lbl = self.slider_row(g, 1, "交叉饋送", "像聽喇叭、不累", self.crossfeed, 0, 3, 1, 180, num=False)
        self.bal_lbl = self.slider_row(g, 2, "左右平衡", "補償左右耳", self.balance, -3, 3, 0.5, 180, num=False)
        self.room_lbl = self.slider_row(g, 3, "殘響空間", "錄音室／音樂廳", self.room, 0, 3, 1, 180, num=False)
        self.room_lbl.config(width=10)
        g.columnconfigure(1, weight=1)
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x", pady=(px(8), 0))
        self.label(row, "平衡測試音", 9, bold=True).pack(side="left")
        for where, name in (("R", "右"), ("C", "中央"), ("L", "左")):
            Pill(row, self, name, lambda w=where: self.test_tone(w), size=9).pack(side="right", padx=(px(4), 0))
        self.label(c, "先暫停音樂再按「中央」，偏哪邊就把平衡往另一邊調。", 8, SUB).pack(anchor="w", pady=(px(4), 0))

        # 右：輸出解析度
        c = self.card(right, "輸出解析度", "送給 DAC 的格式")
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x")
        self.label(row, "位元深度", 9, SUB, width=7, anchor="w").pack(side="left")
        self.depth_pills = {}
        for bits in DEPTHS:
            p = Pill(row, self, f"{bits}-bit", lambda b=bits: self.pick_format(bits=b), size=9, font=NUM)
            p.pack(side="left", padx=(0, px(4)))
            self.depth_pills[bits] = p
        self.label(c, "取樣率（kHz）", 9, SUB).pack(anchor="w", pady=(px(6), px(2)))
        grid = tk.Frame(c, bg=PANEL)
        grid.pack(fill="x")
        self.rate_pills = {}
        for i, rate in enumerate(RATES):
            p = Pill(grid, self, f"{rate / 1000:g}", lambda x=rate: self.pick_format(rate=x), size=9, font=NUM)
            p.grid(row=i // 4, column=i % 4, sticky="ew", padx=px(2), pady=px(2))
            self.rate_pills[rate] = p
        grid.columnconfigure((0, 1, 2, 3), weight=1, uniform="r")
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x", pady=(px(6), 0))
        self.fmt_lbl = self.label(row, "", 9, VALUE)
        self.fmt_lbl.pack(side="left")
        self.apply_btn = Pill(row, self, "套用", self.apply_format, size=9)
        self.apply_btn.pack(side="right")
        self.label(c, "播放程式會把歌曲轉成這個格式。CD 音源用 44.1 的倍數\n（88.2／176.4／352.8）最單純；切換時音樂會停一下，再按播放。",
                   8, SUB, justify="left").pack(anchor="w", pady=(px(6), 0))

        # 右：我的預設
        c = self.card(right, "我的預設", "調好停 20 秒會自動存")
        row = tk.Frame(c, bg=PANEL)  # 一排放完：下拉選單＋儲存＋刪除
        row.pack(fill="x")
        Pill(row, self, "刪除", self.delete_preset).pack(side="right")
        Pill(row, self, "儲存", self.save_preset, primary=True).pack(side="right", padx=px(6))
        self.preset_box = ttk.Combobox(row, state="readonly", font=(FONT, 10), style="Dark.TCombobox", width=14)
        self.preset_box.pack(side="left", fill="x", expand=True)
        self.preset_box.bind("<<ComboboxSelected>>", self.load_preset)
        self.refresh_presets()

        # 底部狀態列
        foot = tk.Frame(r, bg=BG)
        foot.pack(fill="x", padx=px(16), pady=(0, px(10)))
        self.status = self.label(foot, "", 9, GREEN, anchor="w")
        self.status.pack(side="left")
        self.hk_lbl = self.label(foot, "快捷鍵　" + "　".join(f"{n} {d}" for _i, _m, _v, n, d in HOTKEYS), 9, SUB)
        self.hk_lbl.pack(side="right")

    def build_base_pills(self):
        px = self.px
        for w in self.base_grid.winfo_children():
            w.destroy()
        self.base_pills = {}
        items = list(BASES.items())
        for i, (key, (name, _f)) in enumerate(items):
            p = Pill(self.base_grid, self, name, lambda k=key: self.pick_base(k), size=9)
            alone = i == len(items) - 1 and i % 2 == 0
            p.grid(row=i // 2, column=i % 2, columnspan=2 if alone else 1, sticky="ew", padx=px(2), pady=px(2))
            self.base_pills[key] = p
        for row in range((len(items) + 1) // 2, 3):  # 補空白到 3 排
            tk.Label(self.base_grid, text=" ", font=(FONT, 9), bg=PANEL, pady=px(5)).grid(row=row, column=0, pady=px(2))

    def paint_header(self):
        cut = lambda t, n: t if len(t) <= n else t[:n - 1] + "…"
        self.hp_btn.config(text="耳機：" + cut((self.hp or {}).get("name") or "還沒選（點我選）", 30))
        dev = find_device(self.dev_guid)
        self.devsel_btn.config(text="輸出：" + cut(dev["name"] if dev else "還沒選（點我選）", 30))

    # ---------- 選耳機、選裝置 ----------
    def dialog(self, title, hint):
        px = self.px
        win = tk.Toplevel(self.root, bg=PANEL)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        self.label(win, hint, 10, SUB, justify="left").pack(anchor="w", padx=px(16), pady=(px(12), px(6)))
        return win

    def choose_headphone(self):
        px = self.px
        win = self.dialog("選擇耳機", "輸入耳機型號（例：HD 600、XM5、AirPods Max），資料來自 AutoEQ 資料庫")
        entry = tk.Entry(win, font=(FONT, 12), relief="flat", bg=PILL, fg=TEXT, insertbackground=TEXT)
        entry.pack(fill="x", padx=px(16), ipady=px(4))
        box = tk.Listbox(win, font=(FONT, 10), height=14, width=56, relief="flat", bg=PANEL, fg=TEXT,
                         selectbackground=ACCENT, selectforeground="white", highlightthickness=1,
                         highlightbackground=LINE, activestyle="none")
        box.pack(fill="both", padx=px(16), pady=px(8))
        msg = self.label(win, "下載耳機清單中…", 9, SUB)
        msg.pack(anchor="w", padx=px(16))
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=px(16), pady=(px(6), px(14)))
        state = {"models": {}, "shown": []}

        def refilter(_e=None):
            q = re.sub(r"[^0-9a-z]", "", entry.get().lower())
            hits = [n for n in state["models"] if q and q in re.sub(r"[^0-9a-z]", "", n.lower())] if q else []
            hits.sort(key=lambda n: (len(n), n))
            state["shown"] = hits[:300]
            box.delete(0, "end")
            for n in state["shown"]:
                srcs = sorted({src for src, _p in state["models"][n]})
                box.insert("end", f"{n}　（{len(srcs)} 份量測）")
            msg.config(text=f"找到 {len(hits)} 個" if q else f"共 {len(state['models'])} 款耳機，輸入型號搜尋")

        def loaded(models, err):
            if not win.winfo_exists():
                return
            if err:
                msg.config(text=f"耳機清單下載失敗：{err}", fg=ORANGE)
                return
            state["models"] = models
            refilter()

        def pick(_e=None):
            sel = box.curselection()
            if not sel:
                return
            name = state["shown"][sel[0]]
            msg.config(text=f"下載「{name}」的校正資料中…", fg=SUB)
            threading.Thread(target=lambda: self.root.after(0, done, name, *download_headphone(name, state["models"][name])),
                             daemon=True).start()

        def done(name, sources, err):
            if err or not sources:
                if win.winfo_exists():
                    msg.config(text=f"下載失敗：{err or '沒有可用的資料'}", fg=ORANGE)
                return
            self.set_hp({"name": name, "sources": sources})
            if win.winfo_exists():
                win.destroy()

        def none():
            self.set_hp({"name": "不校正", "sources": []})
            win.destroy()

        Pill(row, self, "用這支", pick, primary=True).pack(side="right")
        Pill(row, self, "找不到，先不校正", none, size=9).pack(side="right", padx=px(6))
        entry.bind("<KeyRelease>", refilter)
        box.bind("<Double-Button-1>", pick)
        entry.focus_set()
        threading.Thread(target=lambda: self.root.after(0, loaded, *load_headphone_index()), daemon=True).start()

    def set_hp(self, hp):
        self.hp = hp
        set_headphone(hp)
        update_headroom()
        self.build_base_pills()
        self.base.set(default_base())
        self.paint_header()
        self.changed()
        self.toast(f"耳機：{hp['name']}（音量預留 {HEADROOM:g} dB）")

    def choose_device(self):
        px = self.px
        win = self.dialog("選擇輸出裝置", "選你的耳機插在哪個裝置（解碼器、耳擴、音效卡）。\n標「已接上」的才會經過 Equalizer APO。")
        devs = sorted((d for d in list_devices() if d["active"]), key=lambda d: (not d["hooked"], d["name"]))
        for d in devs:
            tag = "已接上" if d["hooked"] else "還沒接上"
            p = Pill(win, self, f"{d['name']}　（{tag}）", lambda d=d: (self.set_device(d), win.destroy()), size=10)
            p.set_selected(d["guid"].lower() == (self.dev_guid or "").lower())
            p.pack(fill="x", padx=px(16), pady=px(3))
        if not devs:
            self.label(win, "沒有偵測到任何輸出裝置", 10, ORANGE).pack(padx=px(16))
        tk.Frame(win, bg=PANEL, height=px(12)).pack()

    def set_device(self, dev):
        self.dev_guid = dev["guid"]
        self.paint_header()
        if os.path.isdir(self.cfg_dir):
            self.setup_config()
        self.save_settings()
        if not dev["hooked"]:
            self.open_selector()

    def toggle_row(self, parent, title, sub, var, command):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=self.px(3))
        Toggle(row, self, var, command).pack(side="right")
        self.label(row, title, 10, bold=True).pack(anchor="w")
        self.label(row, sub, 8, SUB).pack(anchor="w")

    def show_group(self, gi):
        """切換快速風格分頁；每頁固定一樣多格（依最多的那頁），數量不足補空白，版面高度才不會變"""
        px = self.px
        self.group = gi
        for i, (lbl, bar) in enumerate(self.tabs):
            lbl.config(fg=TEXT if i == gi else SUB)
            bar.config(bg=ACCENT if i == gi else PANEL)
        for w in self.style_grid.winfo_children():
            w.destroy()
        self.style_btns = {}
        start = sum(len(g) for _n, g in STYLE_GROUPS[:gi])
        group = STYLE_GROUPS[gi][1]
        for j in range(3 * math.ceil(max(len(g) for _n, g in STYLE_GROUPS) / 3)):
            if j < len(group):
                name, vals, width, cf, _src = group[j]
                w = Pill(self.style_grid, self, name, lambda i=start + j: self.apply_style(i), size=9)
                self.style_btns[start + j] = w
                w.bind("<Enter>", lambda _e, i=start + j: self.show_info(i), add="+")
                w.bind("<Leave>", lambda _e: self.show_info(self.current_style()), add="+")
            else:
                w = tk.Label(self.style_grid, text=" ", font=(FONT, 9), bg=PANEL, pady=px(5))
            w.grid(row=j // 3, column=j % 3, sticky="ew", padx=px(2), pady=px(2))
        self.style_grid.columnconfigure((0, 1, 2), weight=1, uniform="s")
        self.highlight_style(self.current_style())

    @staticmethod
    def group_of(idx):
        for gi, (_n, group) in enumerate(STYLE_GROUPS):
            if idx < len(group):
                return gi
            idx -= len(group)
        return 0

    def highlight_style(self, idx):
        for i, b in self.style_btns.items():
            b.set_selected(i == idx)
        self.show_info(idx)

    def show_info(self, idx):
        """說明框：名字＋白話介紹（滑鼠移到按鈕上會先預覽）"""
        if idx >= 0:
            self.style_name.config(text=STYLES[idx][0])
            self.style_plain.config(text=PLAIN[STYLES[idx][0]])
        else:
            self.style_name.config(text="自訂調音")
            self.style_plain.config(text="跟內建風格都不一樣，喜歡可以存到「我的預設」")

    def slider_row(self, g, row, name, hint, var, lo, hi, step, length, num=True):
        px = self.px
        lab = tk.Frame(g, bg=PANEL)
        lab.grid(row=row, column=0, sticky="w", pady=px(3))
        self.label(lab, name, 10, bold=True).pack(anchor="w")
        self.label(lab, hint, 8, SUB).pack(anchor="w")
        Slider(g, self, var, lo, hi, step, length, self.changed).grid(row=row, column=1, sticky="ew", padx=px(10))
        v = self.label(g, "", 10, VALUE, font=NUM if num else None, width=7, anchor="e")
        v.grid(row=row, column=2)
        return v

    def fit_style_grid(self):
        """每個分頁的按鈕名稱長短不同：量出最大的，把按鈕區固定成那個大小，切換分頁版面就不會動"""
        w = h = 0
        for gi in range(len(STYLE_GROUPS)):
            self.show_group(gi)
            self.style_grid.update_idletasks()
            w = max(w, self.style_grid.winfo_reqwidth())
            h = max(h, self.style_grid.winfo_reqheight())
        self.style_grid.grid_propagate(False)
        self.style_grid.config(width=w, height=h)
        self.show_group(0)

    def fit_source_box(self):
        """說明框：寬度跟著卡片、高度取所有風格裡最高的白話介紹＋最高的依據"""
        width = self.src_box.winfo_width()
        if width < self.px(100):  # 視窗還沒顯示時量不到，就用卡片需要的寬度
            width = self.src_box.master.winfo_reqwidth()
        tall = {}
        for lbl, texts in ((self.style_name, [n for n, *_r in STYLES]),
                           (self.style_plain, list(PLAIN.values()))):
            lbl.config(wraplength=width - 2 * self.px(10))
            tall[lbl] = 0
            for t in texts:
                lbl.config(text=t)
                lbl.update_idletasks()
                tall[lbl] = max(tall[lbl], lbl.winfo_reqheight())
        self.src_box.config(height=sum(tall.values()) + self.px(12))

    # ---------- 每 2 秒更新：裝置、輸出格式、播放資訊 ----------
    def tick(self):
        dev = find_device(self.dev_guid)
        self.refresh_device(dev)
        self.refresh_format(dev)
        self.refresh_playback(dev)
        self.root.after(2000, self.tick)

    def refresh_device(self, dev):
        if dev and dev["hooked"] and dev["active"]:
            self.dev_chip.config(text="● EQ 已接上", fg=GREEN, bg=GREEN_BG)
            self.fix_btn.pack_forget()
            return
        text = ("● EQ 還沒接上這個裝置" if dev["active"] else "● 裝置沒插上") if dev else "● 還沒選輸出裝置"
        dev = dev if dev and dev["active"] and not dev["hooked"] else None
        self.dev_chip.config(text=text, fg=ORANGE, bg=ORANGE_BG)
        if dev and not self.fix_btn.winfo_ismapped():
            self.fix_btn.pack(side="right")

    def open_selector(self):
        apo = os.path.dirname(self.cfg_dir)
        # 一定要從安裝資料夾啟動，不然會出現 Qt platform plugin 錯誤
        ctypes.windll.shell32.ShellExecuteW(None, "runas", os.path.join(apo, "DeviceSelector.exe"), None, apo, 1)
        dev = find_device(self.dev_guid)
        name = dev["iface"] if dev else "你的輸出裝置"
        messagebox.showinfo("接上 EQ", f"在跳出的視窗勾選「{name}」→ 按確定，\n然後重新開機就完成了。", parent=self.root)

    def refresh_format(self, dev):
        cur = parse_fmt(dev["fmt"]) if dev and dev["active"] else None
        self.cur_fmt = cur[:2] if cur else None
        if self.cur_fmt and int(self.room.get()) and self.cur_fmt[1] != getattr(self, "_ir_rate", None):
            self.changed()  # DAC 取樣率變了 → 殘響檔換成新的取樣率
        if self.pend_fmt is None and self.cur_fmt:
            self.pend_fmt = self.cur_fmt
        self.paint_format()

    def pick_format(self, bits=None, rate=None):
        if not self.pend_fmt:
            return
        self.pend_fmt = (bits or self.pend_fmt[0], rate or self.pend_fmt[1])
        self.paint_format()

    def paint_format(self):
        if not self.cur_fmt:
            self.fmt_lbl.config(text="沒偵測到 DAC")
            return
        pb, pr = self.pend_fmt
        for bits, p in self.depth_pills.items():
            p.set_selected(bits == pb)
        for rate, p in self.rate_pills.items():
            p.set_selected(rate == pr)
        changed = self.pend_fmt != self.cur_fmt
        self.fmt_lbl.config(text=f"目前 {self.cur_fmt[0]}-bit / {fmt_rate(self.cur_fmt[1])}"
                                 + ("　→ 按套用" if changed else ""))
        if self.apply_btn.primary != changed:
            self.apply_btn.primary = changed
            self.apply_btn.paint()

    def apply_format(self):
        dev = find_device(self.dev_guid)
        if not dev or not dev["active"] or not self.pend_fmt:
            messagebox.showinfo("輸出解析度", "沒偵測到插著的輸出裝置。", parent=self.root)
            return
        if self.pend_fmt == self.cur_fmt:
            self.toast("已經是這個格式了")
            return
        bits, rate = self.pend_fmt
        try:
            set_device_format(dev["guid"], bits, rate)
        except Exception as e:
            messagebox.showerror("輸出解析度", f"DAC 不接受 {bits}-bit / {fmt_rate(rate)}：\n{e}", parent=self.root)
            self.pend_fmt = self.cur_fmt
            self.paint_format()
            return
        self.toast(f"輸出格式：{bits}-bit / {fmt_rate(rate)}")
        self.root.after(800, lambda: self.refresh_format(find_device(self.dev_guid)))

    def refresh_playback(self, dev):
        ch = self.chips
        info = read_tidal_status()
        dac = parse_fmt(dev["fmt"]) if dev and dev["active"] else None

        def put(key, text, fg=TEXT, bg=PILL):
            ch[key].config(text=text, fg=fg, bg=bg if text else BG, padx=self.px(10) if text else 0)

        other = None if info.get("state") == "active" and "src" in info else other_player(self.dev_guid)
        if other:  # Tidal 沒在播、別的程式在出聲（例如瀏覽器的 YouTube Music）：一樣經過 EQ
            yt = youtube_window() if other.lower() in BROWSERS or "youtube" in other.lower() else None
            app = BROWSERS.get(other.lower(), other.rsplit(".", 1)[0])
            put("state", f"▶ 播放中：{yt}（{app}）" if yt and yt.lower() not in app.lower() else f"▶ 播放中：{app}", GREEN, GREEN_BG)
            put("src", "有損串流 AAC／Opus" if yt else "")
            put("kind", "約 128–256 kbps" if yt else "", CD_FG, CD_BG)
            put("rate", "")
            ch["arrow"].config(text="→", fg=SUB, bg=BG)
            put("dac", f"DAC {dac[0]}-bit / {fmt_rate(dac[1])}" if dac else "")
            put("mode", "共用模式 · EQ 有效", GREEN, GREEN_BG)
            return
        if "src" not in info:
            put("state", "還沒偵測到播放（播一首歌就會顯示）", SUB)
            for k in ("src", "kind", "rate", "arrow", "dac", "mode"):
                put(k, "")
            return
        n, bits, rate = info["src"]
        playing = info.get("state") == "active"
        put("state", "▶ 播放中" if playing else "⏸ 暫停中", GREEN if playing else SUB, GREEN_BG if playing else PILL)
        put("src", f"歌曲 {bits}-bit / {fmt_rate(rate)}")
        hires = bits > 16 or rate > 48000
        put("kind", "Hi-Res 無損" if hires else "CD 無損", GOLD if hires else CD_FG, GOLD_BG if hires else CD_BG)
        rt, avg = info.get("rt_kbps"), info.get("avg_kbps")
        if not playing:
            txt = "位元率 —"
        elif info.get("done"):
            txt = "實時 —（尾段已下載完）"
        elif rt:
            txt = f"實時 {rt:.0f} kbps"
        else:
            txt = "實時 計算中…"
        put("rate", txt + (f" · 平均 {avg:.0f}" if avg else ""))
        ch["arrow"].config(text="→", fg=SUB, bg=BG)
        out = info.get("out")
        if out and (info.get("mode") == "exclusive"
                    or (info.get("mode") is None and dac and out[1] == rate and out[1] != dac[1])):
            put("dac", f"DAC {out[0]}-bit / {fmt_rate(out[1])}")
            put("mode", "獨佔模式 · EQ 不會生效", ORANGE, ORANGE_BG)
        elif dac:
            put("dac", f"DAC {dac[0]}-bit / {fmt_rate(dac[1])}")
            put("mode", "共用模式 · EQ 有效", GREEN, GREEN_BG)
        else:
            put("dac", "")
            put("mode", "")

    # ---------- 調整 ----------
    def toggle_passthrough(self):
        if self.passthrough.get() and not messagebox.askokcancel(
                "直通模式",
                f"直通模式完全不處理聲音，也不會預留音量，\n聲音會突然變大約 {HEADROOM:g} dB（約 3 倍大聲）。\n\n"
                "請先把解碼器／耳擴的音量轉小，再按「確定」。", parent=self.root):
            self.passthrough.set(False)
        self.changed()

    def pick_base(self, key):
        self.base.set(key)
        self.changed()

    def filters(self):
        base = BASES[self.base.get()][1]
        style = [(k, f, round(v.get(), 1), q) for (_n, k, f, q, _h), v in zip(BANDS, self.bands) if v.get()]
        return list(base), style

    def set_bands(self, vals, width=None, crossfeed=None, room=None):
        for var, v in zip(self.bands, vals):
            var.set(v)
        if width is not None:
            self.width.set(width)
        if crossfeed is not None:
            self.crossfeed.set(crossfeed)
        if room is not None:
            self.room.set(room)
        self.changed()

    def apply_style(self, idx):
        name, vals, width, cf, _src = STYLES[idx]
        self.set_bands(vals, width, cf, STYLE_ROOM.get(name, 0))

    def current_style(self):
        """目前的設定跟哪個內建風格一樣；都不一樣回傳 -1"""
        cur = ([round(v.get(), 1) for v in self.bands], round(self.width.get()), int(self.crossfeed.get()),
               int(self.room.get()))
        start = sum(len(g) for _n, g in STYLE_GROUPS[:self.group])
        order = list(range(start, start + len(STYLE_GROUPS[self.group][1]))) + list(range(len(STYLES)))
        return next((i for i in order if ([round(float(x), 1) for x in STYLES[i][1]], STYLES[i][2], STYLES[i][3],
                                          STYLE_ROOM.get(STYLES[i][0], 0)) == cur), -1)

    def changed(self, *_):
        for var, lbl in zip(self.bands, self.val_lbls):
            v = var.get()
            lbl.config(text=f"{v:+.1f} dB" if v else "0 dB")
        w = self.width.get()
        self.width_lbl.config(text=f"+{w:.0f}%" if w else "0%")
        self.cf_lbl.config(text=CROSSFEED[int(self.crossfeed.get())][0])
        b = self.balance.get()
        self.bal_lbl.config(text="置中" if not b else f"{'偏右' if b > 0 else '偏左'} {abs(b):g}")
        self.room_lbl.config(text=ROOMS[int(self.room.get())][0])
        for key, p in self.base_pills.items():
            p.set_selected(key == self.base.get())
        # 目前的調音跟哪個風格一樣就標藍色；在別的分頁就自動切過去
        idx = self.current_style()
        if idx >= 0 and idx not in self.style_btns:
            self.show_group(self.group_of(idx))
        else:
            self.highlight_style(idx)
        now = self.preset_key(self.snapshot())
        self.preset_box.set(next((n for n, p in self.presets.items() if self.preset_key(p) == now), ""))
        if self._auto_job:
            self.root.after_cancel(self._auto_job)
        self._auto_job = self.root.after(20000, self.autosave)
        self.redraw()
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(250, self.write_config)

    def redraw(self):
        px, cv = self.px, self.canvas
        cv.delete("all")
        W, H = self.cw, self.ch
        L, R, T, B = px(34), px(8), px(8), px(20)

        def x(f):
            return L + (W - L - R) * math.log10(f / 20) / 3

        def y(db):
            return T + (H - T - B) * (12 - max(-12, min(12, db))) / 24

        for f in (50, 200, 500, 2000, 5000):
            cv.create_line(x(f), T, x(f), H - B, fill=GRID_MINOR)
        for f, t in ((100, "100"), (1000, "1k"), (10000, "10k")):
            cv.create_line(x(f), T, x(f), H - B, fill=LINE)
            cv.create_text(x(f), H - B + px(3), text=t, anchor="n", fill=SUB, font=(NUM, 8))
        for db in (-12, -6, 6, 12):
            cv.create_line(L, y(db), W - R, y(db), fill=GRID_MINOR if abs(db) == 12 else LINE)
            cv.create_text(L - px(6), y(db), text=f"{db:+d}", anchor="e", fill=SUB, font=(NUM, 8))
        cv.create_text(L - px(6), y(0), text="0", anchor="e", fill=SUB, font=(NUM, 8))
        base, style = self.filters()
        on = self.enabled.get() and not self.passthrough.get()
        total = curve(base + style) if on and (base or style) else [0.0] * len(FREQS)
        pts = [c for f, db in zip(FREQS, total) for c in (x(f), y(db))]
        cv.create_polygon(x(FREQS[0]), y(0), *pts, x(FREQS[-1]), y(0), fill=FILL, outline="")
        cv.create_line(L, y(0), W - R, y(0), fill=ZERO_LINE)
        if on and style:
            spts = [c for f, db in zip(FREQS, curve(style)) for c in (x(f), y(db))]
            cv.create_line(*spts, fill=ORANGE, width=px(1.5), dash=(4, 3))
        cv.create_line(*pts, fill=ACCENT if on else SUB, width=px(2.5), smooth=False)
        if not on:
            msg = "直通模式：完全不處理（最接近獨佔模式）" if self.passthrough.get() else "EQ 已關閉（原音，音量不變）"
            cv.create_text(W / 2, T + px(16), text=msg, fill=SUB, font=(FONT, 10, "bold"))
            return
        notes = []
        if self.width.get():
            notes.append(f"聲場寬度 +{self.width.get():.0f}%")
        if int(self.crossfeed.get()):
            notes.append(f"交叉饋送：{CROSSFEED[int(self.crossfeed.get())][0]}")
        if self.balance.get():
            notes.append(f"平衡：{self.bal_lbl.cget('text')}")
        if int(self.room.get()):
            notes.append(f"殘響：{ROOMS[int(self.room.get())][0]}")
        if notes:
            cv.create_text(W - R - px(4), T + px(4), anchor="ne", text="　".join(notes),
                           fill=ORANGE, font=(FONT, 9, "bold"))

    def write_config(self):
        self._job = None
        base, style = self.filters()
        through = self.passthrough.get()
        on = self.enabled.get() and not through
        room, reverb_file, room_db, note = int(self.room.get()), "", None, ""
        if room:
            if not self.cur_fmt:
                note = "（沒偵測到 DAC 取樣率，殘響暫停）"
            else:
                try:
                    reverb_file = room_file(self.cfg_dir, room, self.cur_fmt[1])
                    room_db = room_gain(self.cfg_dir, reverb_file)
                    self._ir_rate = self.cur_fmt[1]
                except Exception as e:  # 沒有 numpy 或寫不進去
                    note = f"（殘響做不出來：{e}）"
        args = (base + style, self.width.get(), int(self.crossfeed.get()), self.balance.get(), reverb_file, room_db)
        # 殘響才自動多降（用實際算出的最壞增益）；EQ 關掉時也用同一個音量，A/B 比較才公平
        extra = max(0.0, build_config(*args)[1] - HEADROOM) if reverb_file else 0.0
        text, peak = build_config(*args, extra) if on else build_config([], extra=extra)
        if through:  # 不寫 Preamp、不寫任何濾波器 → 訊號原封不動
            text = "# written by headphone tuner\n# passthrough: no processing\n"
        try:
            with open(os.path.join(self.cfg_dir, OUT_NAME), "w", encoding="ascii") as fh:
                fh.write(text)
            try:
                os.utime(os.path.join(self.cfg_dir, "config.txt"))  # 提醒 Equalizer APO 重新讀取
            except OSError:
                pass
            if through:
                self.status.config(text="✓ 直通模式：訊號完全不處理（EQ、聲場、固定降音量都暫停）", fg=GREEN)
            elif peak > HEADROOM + extra + 0.05:
                self.status.config(text=f"⚠ 已套用，但最高加強 +{peak:.1f} dB 超過預留的 {HEADROOM:g} dB，"
                                        "很大聲的段落可能破音（把加強的滑桿調少一點）", fg=ORANGE)
            else:
                msg = (f"✓ 已套用　殘響開啟：整體多降 {extra:.1f} dB 防破音（開關 EQ 音量仍一樣）" if extra else
                       "✓ 已套用　音量固定，切換設定、開關 EQ 音量都一樣　（關掉視窗 EQ 仍然有效）")
                self.status.config(text=msg + note, fg=ORANGE if note else GREEN)
        except PermissionError:
            self.status.config(text="✗ 沒有權限寫入 Equalizer APO 的設定資料夾", fg=ORANGE)
            self.fix_permission()
        except OSError as e:
            self.status.config(text=f"✗ 寫入失敗：{e}", fg=ORANGE)
        self.save_settings()

    def test_tone(self, where):
        """在選定的裝置播 4 秒粉紅噪音（會經過 EQ，所以能用來校正左右平衡）"""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            messagebox.showinfo("測試音", "需要先安裝 numpy 和 sounddevice 這兩個套件。", parent=self.root)
            return
        try:
            api = next(i for i, a in enumerate(sd.query_hostapis()) if "WASAPI" in a["name"])
            want = find_device(self.dev_guid)
            dev = next(i for i, d in enumerate(sd.query_devices())
                       if d["hostapi"] == api and d["max_output_channels"] >= 2 and want and want["iface"] in d["name"])
            sr = int(sd.query_devices(dev)["default_samplerate"])
            n = sr * 4
            spec = np.fft.rfft(np.random.default_rng().standard_normal(n))
            k = np.arange(len(spec), dtype=float)
            k[0] = 1
            pink = np.fft.irfft(spec / np.sqrt(k), n)  # 粉紅噪音：每個八度能量一樣，最接近音樂
            pink *= 0.05 / np.sqrt((pink ** 2).mean())  # 約 -26 dBFS，很小聲
            pink *= np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (sr * 0.05))  # 淡入淡出
            gl, gr = {"L": (1, 0), "C": (1, 1), "R": (0, 1)}[where]
            sd.play(np.column_stack([pink * gl, pink * gr]).astype("float32"), sr, device=dev)
            self.toast({"L": "測試音：左", "C": "測試音：中央（應該在正中間）", "R": "測試音：右"}[where])
        except Exception as e:
            messagebox.showerror("測試音", f"播放失敗：{e}", parent=self.root)

    # ---------- 快捷鍵 ----------
    def toast(self, text):
        """螢幕右下角跳一個小提示（在 Tidal 裡按快捷鍵也看得到）"""
        if self._toast:
            self._toast.destroy()
        t = self._toast = tk.Toplevel(self.root, bg=ACCENT)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=text, font=(FONT, 12, "bold"), fg=TEXT, bg=HEADER,
                 padx=self.px(20), pady=self.px(12)).pack(padx=self.px(2), pady=self.px(2))
        t.update_idletasks()
        x = t.winfo_screenwidth() - t.winfo_width() - self.px(24)
        y = t.winfo_screenheight() - t.winfo_height() - self.px(80)
        t.geometry(f"+{x}+{y}")
        t.after(1300, t.destroy)

    def hotkey_toggle_eq(self):
        if self.passthrough.get():
            self.toast("直通模式中，請先在調音台取消直通")
            return
        self.enabled.set(not self.enabled.get())
        self.changed()
        self.toast("EQ 開" if self.enabled.get() else "EQ 關（原音）")

    def hotkey_style(self, step):
        idx = self.current_style()
        idx = (idx + step) % len(STYLES) if idx >= 0 else 0
        self.apply_style(idx)
        name = STYLES[idx][0]
        self.toast(f"風格：{name}")

    def hotkey_failed(self, name):
        self.hk_lbl.config(text=f"⚠ {name} 被別的程式佔用了", fg=ORANGE)

    def reset_default(self):
        self.enabled.set(True)
        self.base.set(default_base())
        self.crossfeed.set(0)
        self.balance.set(0)
        self.set_bands([0] * len(BANDS), 0, room=0)

    # ---------- 預設 ----------
    def snapshot(self):
        return {"enabled": self.enabled.get(), "base": self.base.get(),
                "bands": [v.get() for v in self.bands], "width": self.width.get(),
                "passthrough": self.passthrough.get(), "crossfeed": int(self.crossfeed.get()),
                "balance": self.balance.get(), "room": int(self.room.get())}

    def save_settings(self):
        data = {"last": self.snapshot(), "presets": self.presets, "headphone": self.hp, "device": self.dev_guid}
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def refresh_presets(self):
        mine = sorted(n for n in self.presets if not n.startswith(AUTO))
        autos = sorted((n for n in self.presets if n.startswith(AUTO)), reverse=True)  # 新的在前
        self.preset_box["values"] = mine + autos

    @staticmethod
    def preset_key(p):
        return (p.get("base", "autoeq"), [round(float(x), 1) for x in p.get("bands", [])],
                round(p.get("width", 0)), int(p.get("crossfeed", 0)), round(p.get("balance", 0), 1), int(p.get("room", 0)))

    def autosave(self):
        """設定停 20 秒沒再改就自動存成預設；重複的不存，自動存檔只留最新 10 個"""
        self._auto_job = None
        snap = self.snapshot()
        if snap["passthrough"] or not snap["enabled"]:
            return
        key = self.preset_key(snap)
        if any(self.preset_key(p) == key for p in self.presets.values()):
            return
        name = datetime.now().strftime(AUTO + "%m/%d %H:%M")
        if name in self.presets:
            name = datetime.now().strftime(AUTO + "%m/%d %H:%M:%S")
        self.presets[name] = {k: snap[k] for k in ("base", "bands", "width", "crossfeed", "balance", "room")}
        for old in sorted(n for n in self.presets if n.startswith(AUTO))[:-10]:
            del self.presets[old]
        self.refresh_presets()
        self.preset_box.set(name)
        self.save_settings()

    def on_close(self):
        if self._job:  # 還沒寫進 EQ 的改動先寫進去
            self.write_config()
        if self._auto_job:
            self.autosave()
        self.root.destroy()

    def save_preset(self):
        name = simpledialog.askstring("儲存預設", "幫這組設定取個名字：", parent=self.root)
        name = (name or "").strip()
        if not name:
            return
        if name in self.presets and not messagebox.askyesno("已經有了", f"「{name}」已存在，要覆蓋嗎？",
                                                            parent=self.root):
            return
        snap = self.snapshot()
        self.presets[name] = {k: snap[k] for k in ("base", "bands", "width", "crossfeed", "balance", "room")}
        self.refresh_presets()
        self.preset_box.set(name)
        self.save_settings()

    def load_preset(self, _e=None):
        p = self.presets.get(self.preset_box.get())
        if p:
            self.base.set(p.get("base") if p.get("base") in BASES else default_base())
            self.balance.set(p.get("balance", 0))
            self.room.set(p.get("room", 0))
            self.set_bands(p.get("bands", [0] * len(BANDS)), p.get("width", 0), p.get("crossfeed", 0))

    def delete_preset(self):
        name = self.preset_box.get()
        if name in self.presets and messagebox.askyesno("刪除", f"確定刪除「{name}」？", parent=self.root):
            del self.presets[name]
            self.preset_box.set("")
            self.refresh_presets()
            self.save_settings()


CONFIG_DIR = None
if __name__ == "__main__":
    if "--uninstall" in sys.argv:  # 解除安裝程式呼叫：把 Equalizer APO 的設定恢復原狀
        try:
            remove_config(sys.argv[sys.argv.index("--uninstall") + 1] if len(sys.argv) > sys.argv.index("--uninstall") + 1
                          else apo_config_dir())
        except OSError as e:
            print("還原 Equalizer APO 設定失敗：", e)
        sys.exit(0)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
    if "--make-shortcut" in sys.argv:  # 安裝.bat 用：建桌面捷徑，再用沒有黑視窗的方式打開調音台
        import subprocess
        try:
            make_shortcut()
        except Exception as e:
            print("捷徑建立失敗：", e)
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(__file__)],
                         cwd=APP_DIR, creationflags=0x00000008)
        sys.exit(0)
    if "--config-dir" in sys.argv:  # 測試用：改寫別的資料夾，不動真正的音效設定
        CONFIG_DIR = sys.argv[sys.argv.index("--config-dir") + 1]
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    mine, mine_plain = analyze_tidal()
    if mine:
        STYLE_GROUPS.append(("你的歌單", mine))
        STYLES.extend(mine)
        PLAIN.update(mine_plain)
    for _k in [k for k in PLAIN if k not in {n for n, *_r in STYLES}]:  # 沒用到的介紹不留（說明框高度依最長的算）
        del PLAIN[_k]
    root = tk.Tk()
    if os.path.exists(ICON_PATH):
        root.iconbitmap(default=ICON_PATH)  # 視窗左上角、工作列、對話框都用調音台圖示
    App(root)
    root.resizable(False, False)
    root.mainloop()
