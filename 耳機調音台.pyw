# -*- coding: utf-8 -*-
"""耳機調音台（通用版）：用中文介面調 Equalizer APO。任何耳機、任何輸出裝置都能用。
耳機校正從 AutoEQ 資料庫下載（目標 Harman）；改動會即時寫進 Equalizer APO 的設定檔，關掉視窗仍然有效。
測試用：加上 --config-dir <資料夾> 可以改寫別的設定資料夾，不會動到真正的音效設定。"""
import base64
import cmath
import ctypes
import ctypes.wintypes
import itertools
import json
import math
import os
import queue
import random
import re
import struct
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import urllib.request
import uuid
import subprocess
import zlib
import winreg
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
ICON_PATH = os.path.join(APP_DIR, "tuner.ico")
APP_ID = "HeadphoneTuner.Panel"  # 工作列用自己的圖示（不跟 Python 混在一起）
ENUM_KEY = "{a45c254e-df1c-4efd-8020-67d146a850e0},24"  # 裝置的匯流排：BTHENUM＝藍牙立體聲、BTHHFENUM＝藍牙通話


def out_name(guid):
    """每個裝置各自的調音設定檔（config.txt 依裝置 Include 對應的檔案）"""
    return f"tuner_{guid.strip('{}')[:8].lower()}.txt"
HP_DIR = os.path.join(APP_DIR, "耳機資料")  # 耳機清單、下載的校正檔快取
AUTOEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
APO_URL = "https://sourceforge.net/projects/equalizerapo/"
# config.txt 裡由調音台管理的區塊（只給選定的裝置用）
BLOCK_BEGIN = "# ==== 耳機調音台：自動管理的區塊，請勿修改 ===="
BLOCK_END = "# ==== 耳機調音台區塊結束 ===="
DUMMY_GUID = "{00000000-0000-0000-0000-000000000000}"
ORIG_MARK = "# 原本的設定（調音台讓它只套用在其他裝置）"
APO_CLSID = "EACD2258"
MM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
NAME_KEY = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"  # 介面名稱（例：TOPPING USB DAC）
DESC_KEY = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"  # 裝置種類（例：喇叭、耳機）
FORMAT_KEY = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"

# 配色：暖色系，奶油白底＋白卡片＋深咖啡字＋陶土橘重點
BG, HEADER, PANEL, LINE = "#FBF5EE", "#FFFCF8", "#FFFFFF", "#EFE2D3"
PILL, PILL_HOVER, TRACK = "#F8EEE3", "#F1E1CF", "#EFE2D3"
TEXT, SUB, VALUE = "#3B2A1E", "#8C7461", "#C0561B"
ACCENT, ACCENT_HI, FILL = "#D9692B", "#E8823F", "#FCE8D8"
GREEN, GREEN_BG, ORANGE, ORANGE_BG = "#4E8A3E", "#EAF3E2", "#B8452B", "#FBE5DE"  # ORANGE＝警告（磚紅）
GOLD, GOLD_BG, CD_FG, CD_BG = "#9A6708", "#FDF0C8", "#C0561B", "#FCE8D8"
GRID_MINOR, ZERO_LINE, KNOB_EDGE = "#F6EEE5", "#E0C9B2", "#E4CFBA"
TWEAK, TIP_BG = "#8A5A36", "#3B2A1E"  # 曲線圖裡「你的細調」（咖啡色虛線）、說明小視窗底色
# 名詞說明：畫面上這些名稱，滑鼠移上去會跳出白話解釋
HELP = {
    "開啟 EQ": "關掉就是原音，音量不會變，方便比較差別。空白鍵也可以開關。",
    "直通模式": "完全不處理聲音、也不預留音量，最接近「獨佔模式」。打開時聲音會突然變大，要先把音量轉小。",
    "耳機校正（AutoEQ 量測，目標 Harman 2018）": "依專業量測，把你的耳機調到研究上最多人喜歡的平衡（Harman 目標）。"
                                            "不同單位量的結果略有差異，「多份平均」最不偏。",
    "低頻": "105 Hz 以下：大鼓、貝斯的量感。",
    "厚度": "250 Hz 附近：聲音飽不飽滿，太多會悶。",
    "人聲": "1.5 kHz 附近：人聲、樂器的主體。",
    "臨場感": "3.5 kHz 附近：清晰、貼近耳邊的感覺，太多會刺耳。",
    "高頻": "10 kHz 以上：亮度、空氣感，太多會嘶嘶的。",
    "聲場寬度": "把左右的差異放大，樂器分得更開、舞台更寬。開太大會有點不自然。",
    "交叉饋送": "喇叭的聲音兩耳都聽得到，耳機卻是左右完全分開。交叉饋送用頭部模型算出前方喇叭繞過頭到另一耳的聲音，"
               "聲音從腦袋中間移到前方，長時間聽比較不累；人聲這類在中間的聲音音色不變。",
    "左右平衡": "左右耳聽力不同、或耳機左右不一樣大聲時用。可以用下面的測試音檢查。",
    "殘響空間": "加上房間的回音：錄音室（小、乾淨）或音樂廳（大、有殿堂感）。回音是照真實房間的形狀做聲學模擬算出來的。",
    "平衡測試音": "播放很小聲的粉紅噪音：按「中央」時聲音應該在正中間。",
    "位元深度": "每個取樣的精細度。選 32-bit，電腦處理完的聲音可以原封不動送給 DAC。",
    "音量優先": "藍牙耳機常常開到最大聲還是不夠大。打開後只預留「目前這組設定」需要的音量空間，會大聲不少；"
               "代價是換風格時音量會跟著變（按住聽原音、開關 EQ 比較時音量仍然一樣）。",
    "取樣率（kHz）": "每秒取樣次數。選 88.2 以上時，調音台會在電腦裡做重建濾波（把 20 kHz 以上濾乾淨，DAC 負擔變小），"
                   "EQ 的高頻也更準。CD、串流多半是 44.1，所以選它的倍數（88.2／176.4／352.8）最好；DAC 不支援就維持原樣。",
}
GUIDE = [
    ("選耳機", "按上方「耳機：」，輸入型號（例：HD 600、XM5），點兩下。藍牙耳機一連上，調音台會自動切過去，"
               "第一次會請你選它的型號；每個裝置各自記住自己的耳機和調音。"),
    ("確認有接上", "右上角要顯示「EQ 已接上」。沒有的話按「點我接上」，勾選你的裝置後重新開機。"),
    ("挑風格", "在「快速風格」點一個，滑鼠移上去會有介紹。也可以在搜尋框打字找（例：搖滾、人聲、低音）。"),
    ("比較差別", "按住上方「按住聽原音」聽原本的聲音，放開就回來；空白鍵也能開關（音量不變）。"),
    ("微調", "拉中間的滑桿；調壞了按「↶ 上一步」或 Ctrl+Z。名稱看不懂？滑鼠移上去就有說明。"),
    ("存起來", "喜歡就按「儲存」；也能「匯出給手機」，在手機的等化器 App 用同一組聲音。"),
]
# 字體：實際用哪個在 pick_fonts() 依電腦上有的決定（中文 Noto Sans TC、數字 Inter）
FONT = FONT_MED = "Microsoft JhengHei UI"
NUM = "Segoe UI"

# 耳機校正：使用者選好耳機後，從 AutoEQ 下載最多 3 份不同來源的量測（目標 Harman），由 set_headphone() 填入
BASES = {"none": ("不校正（耳機原味）", [])}
SOURCE_ORDER = ["oratory1990", "crinacle", "Rtings", "Innerfidelity", "Super Review", "Headphone.com Legacy"]
# AutoEQ 沒有量測、但有同系列兄弟機的型號：名稱 → 用來推估的型號
ESTIMATED = {
    "Sony MDR-XB400（同系列 XB300／XB500 推估）": ["Sony MDR-XB300", "Sony MDR-XB500"],  # 2010 年 Extra Bass 耳罩系列
    # USB-C、Lightning 版 EarPods 跟 3.5mm 版同外殼、同單體，只差接頭（USB-C 版內建小解碼器）
    "Apple EarPods（USB-C／Lightning，同單體）": ["Apple EarPods"],
}


def set_headphone(hp):
    """依耳機資料重建 BASES：第一份來源＝推薦、其餘各一個、兩份以上再加「多份平均」"""
    global _ESTIMATE
    srcs = (hp or {}).get("sources") or []
    _ESTIMATE = (hp or {}).get("name") in ESTIMATED  # 推估的型號：各份都是兄弟機的量測，平均才最接近，所以推薦平均
    BASES.clear()
    cons = None if _ESTIMATE else (hp or {}).get("consensus")
    if cons:  # 所有量測的加權共識（App.start_consensus 背景算好存在 hp 裡）
        BASES["consensus"] = (f"多源共識（{cons[0]} 份，推薦）", [tuple(f) for f in cons[1]])
    for key, (label, fl) in zip(("autoeq", "src2", "src3"), srcs):
        rec = key == "autoeq" and not _ESTIMATE and not cons
        BASES[key] = (f"{label}（推薦）" if rec else f"{label} 量測", [tuple(f) for f in fl])
    if len(srcs) >= 2 and not cons:  # 每個濾波器增益 ÷ 份數疊起來 ≈ 各條校正曲線（dB）的平均，比較不會被單一量測設備帶偏
        BASES["avg"] = ("多份平均（推薦）" if _ESTIMATE else "多份平均（最不偏）",
                        [(t, f, g / len(srcs), q) for _l, fl in srcs for t, f, g, q in fl])
    BASES["none"] = ("不校正（耳機原味）", [])


_ESTIMATE = False


def default_base():
    if "consensus" in BASES:
        return "consensus"
    if _ESTIMATE and "avg" in BASES:
        return "avg"
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
    ("解析度", [-1.5, -1, 0, 0, 0], 10, 0,
     "細節聽不清楚主要是被遮蔽（masking），不是頻寬不夠：低音大聲時會往上遮住中高頻的小聲音（遮蔽向上擴散，Zwicker & Fastl"
     "《Psychoacoustics》）→ 低頻 −1.5、厚度 −1，仍在 Harman 偏好範圍內；高頻不加：靠加高頻得到的「細節」是假的，"
     "只會讓齒音和錄音失真更明顯；不加殘響、不交叉饋送：殘響會降低清晰度指標（C80、D50，ISO 3382）；"
     "樂器在空間上分得越開越容易各自聽清楚（空間遮蔽釋放，Bronkhorst 2000, Acta Acustica）→ 寬度 10%，搭配「分離度：強」"),
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
# 曲風：各曲風的專業數據。平均頻譜很一致、差在低頻和高頻的多寡（Pestana 2013），
# 真正差很多的是音量：古典、爵士動態大、平均音量低（Kirchberger & Russo 2016；Katz K-System），
# Tidal 音量平衡關閉時會比流行小聲 → 用 ISO 226 等響曲線補償
GENRE = [
    ("超級低音衝擊", [4.5, -0.5, -3.5, -3, -4.5], 0, 0,
     "夜店／演唱會 100 dB 在家 80 dB 聽的 ISO 226 等響差，只取 500 Hz 以下（60 Hz 約 +8 dB）；預留空間只夠低頻 +4.5 dB → "
     "其餘頻段一起降約 3 dB，讓低音比中頻多 6.3 dB（≈ Olive 2022 愛低音族群偏好的上限 +6 dB）；代價是整體小約 3 dB，確保不破音"),
    ("蒸汽波／City Pop", [2, 0, 0, 0, -3], 0, 1,
     "卡帶（Type I）頻寬約 30 Hz–15 kHz（±3 dB）→ 高頻 −3 dB；磁帶磁頭的低頻凸起（head bump）→ 低頻 +2 dB；"
     "蒸汽波的 mallsoft 就是在模擬挑高購物中心的殘響 → 約 2 秒的大空間殘響（沿用音樂廳前排的 Beranek 參數）＋輕交叉饋送"),
    ("R&B", [2.5, 0.5, 1, -1, 0.5], 0, 2,
     "R&B 的重點是厚的合成低音（808，約 40–100 Hz）和貼耳的人聲疊音；依製作特色設計，不是量測資料 → "
     "低頻 +2.5 dB（在 Olive & Welti 2015 偏好多低音的範圍內，但比嘻哈的 +4 少），250 Hz 只 +0.5 dB（低頻會往上遮蔽人聲，不能再多），"
     "1.5 kHz +1 dB 讓人聲貼近，3.5 kHz −1 dB 讓疊起來的和聲滑順不尖（刺耳感主要在 2–5 kHz，DIN 45692 尖銳度），10 kHz +0.5 dB 補絲滑的空氣感；"
     "空間：在錄音室用近場喇叭混音 → bs2b 交叉饋送（聲音在前方）"),
    ("嘻哈", [4, -0.5, 0, 1.5, 0], 0, 0,
     "Harman 研究：15% 聽眾偏好多 4–6 dB 低音，年輕聽眾也偏好更多低音（Olive & Welti 2015）→ 低頻 +4 dB；"
     "饒舌靠咬字：低頻會往上遮蔽語音（Zwicker & Fastl）→ 250 Hz −0.5 dB，ANSI S3.5 清晰度權重最高的 2–4 kHz +1.5 dB"),
    ("爵士經典", [1.5, 0.5, 0, 0, 0.5], 0, 3,
     "老爵士母帶普遍比現代流行小聲約 3 dB → ISO 226 等響補償；50–60 年代爵士立體聲常把鼓和管樂硬分左右"
     "（交叉饋送就是為此發明，Bauer 1961）→ bs2b 最強；加 ITU-R BS.1116 小房間殘響 0.25 秒"),
    ("電影／遊戲配樂", [2.5, 1, 0, 0, 1], 20, 1,
     "電影混音標準監聽 85 dB（SMPTE RP 200），在家約 80 dB 聽 → ISO 226 等響補償；加寬 20%＋輕交叉饋送"),
    ("爵士", [2.5, 1, 0, -0.5, 1], 0, 0,
     "爵士母帶約 K-14，比現代流行（約 −8 LUFS）小聲約 5 dB → ISO 226 等響補償（誤差 0.2 dB）"),
    ("古典", [4.5, 2, -0.5, -0.5, 1.5], 0, 1,
     "古典動態最大（Kirchberger & Russo 2016），母帶約 K-20，比流行小聲約 10 dB → ISO 226 等響補償（誤差 0.3 dB）；"
     "空間：古典是為音樂廳寫的 → Beranek 頂級音樂廳數據（殘響 2.0 秒、前排直達/殘響比 +6 dB）＋輕交叉饋送"),
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
     "中文是聲調語言，字義靠基頻與低次諧波（粵語 SII：中低頻權重比英文高，Wong 等 2007, JASA）→ 人聲 1.5 kHz +1.5 dB"),
    ("現場搖滾", [4.5, 2, -0.5, -0.5, 1.5], 0, 2,
     "ISO 226：現場約 90 phon、家裡 80 phon 的等響補償（誤差 0.3 dB）＋bs2b 交叉饋送（現場是聽前方的喇叭）"),
    ("搖滾 Grado 味", [-4.5, 2.5, 1.5, -4, 0], 0, 0,
     "Grado SR325x（搖滾耳機代表）音色走向（oratory1990 量測反推，誤差 1.9 dB）"),
    ("搖滾 V 型", [-1.5, 3, -0.5, 3.5, 6], 0, 0,
     "Beyerdynamic DT 990 Pro（金屬樂常用）音色走向（oratory1990 量測反推，誤差 2.0 dB）"),
    ("搖滾錄音室", [1, 1, 0, -1.5, 3.5], 0, 0,
     "Audio-Technica ATH-M50x（最多人用的錄音室耳機）音色走向（oratory1990 量測反推，誤差 1.6 dB）"),
    ("後朋克／冷波", [0.5, -1.5, 0.5, -0.5, 1.5], 15, 1,
     "Corn Wave 這類後朋克／冷波／空靈搖滾（獨立錄音、吉他疊成一整面牆、貝斯會唱旋律、人聲常被吉他蓋住）；依製作特色設計，不是量測資料 → "
     "250 Hz −1.5 dB 清掉吉他牆的悶（Zwicker & Fastl：低頻會往上遮蔽），低頻 +0.5 dB 讓貝斯圓一點，1.5 kHz +0.5 dB 讓人聲浮出來，"
     "3.5 kHz −0.5 dB 壓失真吉他的毛刺、10 kHz +1.5 dB 補冷亮的空氣感；加寬 15% 把疊起來的吉他分開，"
     "輕度交叉饋送；不加殘響（錄音裡本來就有自己的空間）"),
]
STAGE = [
    ("驚艷試聽", [3, -0.5, 0, -1.5, 2], 35, 4,
     "第一次聽就有感：低頻 +3、高頻 +2 的微笑曲線（第一印象最討喜），厚度 −0.5 讓低音不糊；臨場感 −1.5 壓掉加高頻後容易刺耳的齒音；"
     "虛擬喇叭（聲音在前方，喇叭模式已含錄音室反射 → 不另加殘響）＋寬度 35%：開闊但不像音樂廳那樣有長殘響。"
     "搭配「分離度：強」效果最明顯；長時間聽可能會累"),
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
    ("HD 800 S 大空間", [-4.5, 4, -1.5, 0.5, 5.5], 15, 1,
     "HD 800 S 音色走向（oratory1990 量測反推）＋交叉饋送（輕）＋加寬 15%"),
]
STYLE_ROOM = {"錄音室監聽": 1, "音樂廳前排": 2, "音樂廳中段": 3, "蒸汽波／City Pop": 2, "爵士經典": 1, "古典": 2}  # 風格 → 殘響空間
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
    ("MDR-7506", [-0.5, 0, -0.5, 5, 0], "Sony MDR-7506 錄音室業界標準：中高頻突出、好抓細節（oratory1990 量測反推，誤差 1.5 dB）"),
    ("HIFIMAN Arya", [-4.5, 2.5, -4, 2.5, 1.5], "HIFIMAN Arya 平板旗艦：低頻少、1.5 kHz 內收、高頻稍亮（oratory1990 量測反推，誤差 0.7 dB）"),
    ("Audeze LCD-4", [-3.5, 4.5, 3, -6, 3.5], "Audeze LCD-4 平板旗艦：中低頻厚、3.5 kHz 內收很多（oratory1990 量測反推，誤差 1.5 dB）"),
    ("Focal Clear", [-4, 2, 3, -3, -1.5], "Focal Clear 動圈旗艦：低頻少、中頻飽滿、3.5 kHz 以上收斂（oratory1990 量測反推，誤差 1.2 dB）"),
    ("Sony CD900ST", [-4.5, 4.5, -0.5, -2, -6], "Sony MDR-CD900ST 日本錄音室最常見的監聽耳機：低頻少、中低頻多、高頻收很多（oratory1990 量測反推，誤差 1.6 dB）"))]
POPULAR = [(n, v, 0, 0, s) for n, v, s in (
    ("AirPods Max", [1.5, 1, 0.5, -6, 0.5], "Apple AirPods Max：低頻足、3–4 kHz 內收、聽感柔和（oratory1990 量測反推，誤差 1.3 dB）"),
    ("Sony XM5", [4.5, 5, -3, 4, -1], "Sony WH-1000XM5：低頻加強的熱門聽感（oratory1990 量測反推，誤差 2.1 dB；加強幅度已限制以免破音）"),
    ("Sony XM4", [4.5, 4.5, -2, -1, 2.5], "Sony WH-1000XM4：低頻厚實（oratory1990 量測反推，誤差 1.8 dB；加強幅度已限制以免破音）"),
    ("Bose QC45", [3, 2.5, -0.5, 2.5, 5], "Bose QuietComfort 45：低頻足、高頻亮（oratory1990 量測反推，誤差 1.3 dB）"),
    ("Momentum 4", [4.5, 5, -2, -0.5, 2], "Sennheiser Momentum 4：低頻很多（oratory1990 量測反推，誤差 2.2 dB；加強幅度已限制以免破音）"),
    ("Beats Studio Pro", [1, -5, 1.5, 0.5, 2], "Beats Studio Pro：中低頻乾淨、高頻亮（Rtings 量測反推，誤差 1.5 dB）"),
    ("HD 560S", [-4, 1, 0.5, 0, 1], "Sennheiser HD 560S 平價參考型：低頻少、其餘接近平衡（oratory1990 量測反推，誤差 1.1 dB）"),
    ("HD 58X", [-4.5, 3, 1, -2, -2], "Sennheiser HD 58X Jubilee（HD 650 同系）：低頻少、中低頻多、高頻柔（oratory1990 量測反推，誤差 1.4 dB）"),
    ("DT 770 Pro", [3.5, -1.5, 0.5, -2, 6], "Beyerdynamic DT 770 Pro 監聽耳機：低頻足、高頻很亮（著名的高頻峰值）（oratory1990 量測反推，誤差 1.4 dB）"),
    ("AKG K371", [1.5, 1.5, 0.5, -2.5, -2], "AKG K371（AKG 自己照 Harman 目標調的）：低頻稍多、高頻稍柔（oratory1990 量測反推，誤差 0.9 dB）"),
    ("AKG K701", [-4.5, 3.5, -1.5, -0.5, 1], "AKG K701 經典開放式：低頻少、中低頻稍多（oratory1990 量測反推，誤差 1.2 dB）"),
    ("Philips SHP9500", [-5.5, 1, -1.5, 1, 3], "Philips SHP9500 平價開放式：低頻少、高頻亮（oratory1990 量測反推，誤差 1.4 dB）"),
    ("Koss Porta Pro", [-3, 4.5, 0.5, -2.5, -6], "Koss Porta Pro 復古經典：低頻少、中低頻多、高頻收很多（oratory1990 量測反推，誤差 2.2 dB）"),
    ("Meze 99 Classics", [4, 5, -3, -2, 1.5], "Meze 99 Classics：低頻與中低頻很多、人聲內收（oratory1990 量測反推，誤差 2.1 dB）"),
    ("Sony XM6", [4.5, 2.5, -0.5, -1.5, -6], "Sony WH-1000XM6：低頻多、高頻收很多（單一來源；低音加強幅度已限制以免破音）（Super Review 量測反推，誤差 2.7 dB）"))]
# 平價調音：因為調音好聞名的便宜耳塞（水月雨一類）。同樣是「該耳機相對標準曲線的差異」擬合到細調滑桿；
# 但來源是耳塞的量測（耳塞用耳塞標準曲線、頭戴式用頭戴標準曲線，兩條很像但不完全一樣），只當近似；低音加強限制在 4.5 dB 以免破音
CHEAP = [(n, v, 0, 0, s) for n, v, s in (
    ("水月雨 Chu", [-1.5, 0.5, 0.5, -0.5, 1.5], "水月雨 Moondrop Chu，平價入門款靠調音走紅：整體很接近標準、高頻略亮（oratory1990 耳塞量測反推，誤差 0.6 dB）"),
    ("水月雨 Aria", [0.5, 2, 0, -1.5, 3.5], "水月雨 Moondrop Aria，Hi-Fi 入門名機：中低頻稍厚、3.5 kHz 內收、高頻有空氣感（oratory1990 耳塞量測反推，誤差 1.0 dB）"),
    ("水月雨 Starfield", [0, 2, 1, -1.5, -0.5], "水月雨 Moondrop Starfield：中低頻稍厚、人聲略前、3.5 kHz 內收、高頻柔（oratory1990 耳塞量測反推，誤差 1.3 dB）"),
    ("水月雨 KXXS", [0.5, 2, 0.5, -2, -1.5], "水月雨 Moondrop KXXS：中低頻厚、3.5 kHz 與高頻都收（Super Review 耳塞量測反推，誤差 0.9 dB）"),
    ("Truthear Hexa", [-1, 1.5, 0, -1.5, 4], "Truthear Hexa：接近標準、3.5 kHz 內收、高頻亮（oratory1990 耳塞量測反推，誤差 0.9 dB）"),
    ("Truthear Zero", [-1.5, -1, -0.5, 2, 2], "Truthear x Crinacle Zero：低中頻乾淨、3.5 kHz 與高頻稍亮（oratory1990 耳塞量測反推，誤差 1.1 dB）"),
    ("7Hz Zero", [-0.5, 0.5, 1, -0.5, -0.5], "7Hz Salnotes Zero：整體幾乎貼著標準曲線（oratory1990 耳塞量測反推，誤差 0.8 dB）"),
    ("7Hz Dioko", [-0.5, 0, 2, -4, 6], "7Hz Salnotes Dioko：1.5 kHz 稍多、3.5 kHz 內收很多、高頻亮（oratory1990 耳塞量測反推，誤差 0.9 dB）"),
    ("Tin HiFi T2", [-5.5, 4.5, -1.5, -2.5, 1.5], "Tin HiFi T2 經典平價雙單體：低頻少、中低頻厚、3.5 kHz 內收（oratory1990 耳塞量測反推，誤差 0.9 dB）"),
    ("Etymotic ER2XR", [-1, 1, 3, -2, -3.5], "Etymotic ER2XR：1.5 kHz 人聲區多、3.5 kHz 與高頻收（oratory1990 耳塞量測反推，誤差 1.6 dB）"),
    ("final E1000", [-4.5, 4, -2.5, -1, -1], "final E1000：低頻少、中低頻多、人聲與 3.5 kHz 內收（oratory1990 耳塞量測反推，誤差 1.0 dB）"),
    ("final E3000", [-0.5, 5.5, -3, -3.5, -0.5], "final E3000：中低頻很多、人聲與 3.5 kHz 內收（oratory1990 耳塞量測反推，誤差 1.5 dB）"),
    ("BLON BL-03", [3.5, 3.5, 0, -4, -3], "BLON BL-03：低頻與中低頻多、3.5 kHz 與高頻收（oratory1990 耳塞量測反推，誤差 1.2 dB）"),
    ("Sony EX15LP", [2.5, 3, -2, 0, -3.5], "Sony MDR-EX15LP 超便宜的老牌耳塞：低頻與中低頻多、人聲內收、高頻收（oratory1990 耳塞量測反推，誤差 1.3 dB）"),
    ("TANGZU 無雙", [2.5, 1, 0, -1, 3], "TANGZU Zetian Wu（武則天）：低頻稍多、高頻亮的輕度 V 型（Super Review 耳塞量測反推，誤差 1.1 dB）"))]
# 白話介紹：聽起來怎樣＋適合聽什麼（聽感依曲線描述；「適合」是一般聆聽經驗，不是研究結論）
PLAIN = {
    "只校正": "最平衡、最多人喜歡的標準聲音。什麼音樂都適合（流行、搖滾、華語、K-pop 就用這個）",
    "解析度": "細節最清楚：低音收一點、不加殘響，樂器拉開。搭配「分離度：強」。適合聽錄音細節、古典、爵士",
    "驚艷試聽": "一聽就有感：低音更有力、高音更亮，聲音在前方又很開闊。搭配「分離度：強」。適合展示、短時間聽",
    "多低音族群": "低音更飽、更有衝擊力。適合流行、電子、嘻哈",
    "少低音族群": "低音收一點，清爽乾淨。適合人聲、民謠、長時間聽",
    "女性聽眾偏好": "低音、高音都柔一點，比較溫和。適合抒情、輕音樂",
    "擴散場中性": "錄音室式中性，低音少、高音亮。適合古典、仔細聽錄音",
    "oratory1990": "專業工程師的調音，自然耐聽。什麼音樂都適合",
    "小聲聆聽": "音量開小時把低音和高音補回來。適合深夜、背景音樂",
    "瞬態最好": "起音乾脆、收得快，低音緊不拖尾。鼓、吉他、鋼琴的衝擊感最清楚。適合搖滾、金屬、爵士鼓",
    "喇叭感外化": "聲音從腦袋裡跑到前方，像聽喇叭。適合長時間聽、老錄音",
    "現場搖滾": "補回現場大聲聽的低音衝擊和高音，聲音在前方。適合現場錄音、樂團",
    "搖滾 Grado 味": "低音收、中頻往前，吉他和人聲很有顆粒感。適合經典搖滾、英搖、龐克",
    "搖滾 V 型": "低音有力、高音很亮，鼓和鈸很有衝勁。適合金屬、硬式搖滾",
    "搖滾錄音室": "微 V 型、低音紮實、高音亮。各種搖滾、樂團都適合",
    "嘻哈": "低音飽、饒舌咬字清楚。適合嘻哈、饒舌",
    "爵士": "補回小音量聽不到的低音和空氣感。適合爵士、藍調",
    "古典": "補回古典小聲段落的低音和高音，像坐在音樂廳前排。適合交響、鋼琴、歌劇",
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
    "HIFIMAN Arya": "低音收、人聲稍微退後、高音有空氣感。適合古典、原聲、爵士",
    "Audeze LCD-4": "厚實溫暖、完全不刺耳，中低頻飽滿。適合人聲、爵士、搖滾",
    "Focal Clear": "中頻紮實、高音柔順不刺。適合人聲、搖滾、長時間聽",
    "Sony CD900ST": "低音含蓄、中頻厚、高音很收，是日本錄音室常用的聽法。適合日系歌曲、人聲、細聽混音",
    "HD 560S": "乾淨平衡、低音含蓄，什麼音樂都不挑。適合古典、人聲、遊戲定位",
    "HD 58X": "溫暖柔和、中低頻圓潤、高音不刺。適合人聲、爵士、長時間聽",
    "DT 770 Pro": "低音有力、高音很亮很清楚，但容易刺耳。適合電子、搖滾（刺耳可開「不刺耳」）",
    "AKG K371": "接近標準聲音，低音稍多、高音柔一點。什麼音樂都適合",
    "AKG K701": "輕盈、低音少、其餘接近平衡。適合古典、人聲、原聲樂器",
    "Philips SHP9500": "低音少、高音亮、聲音輕。適合古典、原聲、人聲",
    "Koss Porta Pro": "復古的溫暖，像老收音機：中低頻厚、高音很收。適合老歌、民謠",
    "Meze 99 Classics": "溫暖厚實、低音足、人聲稍退後。適合流行、嘻哈、爵士",
    "Sony XM6": "低音足、聲音柔、高音收。適合流行、電子、通勤",
    "水月雨 Chu": "最接近標準的平價聲音，乾淨自然、高音微亮。什麼音樂都適合",
    "水月雨 Aria": "中低頻稍厚、不刺耳、高音有空氣感。適合人聲、流行、長時間聽",
    "水月雨 Starfield": "溫潤耐聽、人聲稍微往前、高音不刺。適合人聲、民謠、流行",
    "水月雨 KXXS": "厚實柔和、很耐聽，高音不尖。適合人聲、爵士、長時間聽",
    "Truthear Hexa": "乾淨清楚、不刺耳、高音有空氣感。適合流行、原聲、人聲",
    "Truthear Zero": "低音乾淨不糊、細節清楚，稍微偏亮。適合古典、原聲、遊戲",
    "7Hz Zero": "最像標準聲音、什麼都不加不減。適合當作基準來比較",
    "7Hz Dioko": "人聲清楚、中高頻不刺，但高音很亮、很有空氣感。適合人聲、原聲樂器",
    "Tin HiFi T2": "溫暖圓潤、中低頻厚、不刺耳。適合人聲、爵士、搖滾",
    "Etymotic ER2XR": "人聲和樂器的主體很清楚，高音收、不刺。適合人聲、古典、細聽",
    "final E1000": "溫暖柔和、聲音偏暗、完全不刺耳。適合人聲、長時間聽",
    "final E3000": "很溫暖厚實、聲音柔、很不刺耳。適合流行、人聲、夜裡聽",
    "BLON BL-03": "厚實、偏暗、高音很收。適合搖滾、流行、不想刺耳的人",
    "Sony EX15LP": "溫暖柔和、低音厚、聲音偏暗。適合流行、老歌、通勤",
    "TANGZU 無雙": "低音稍足、高音亮、有精神。適合流行、電子、日系",
    "R&B": "低音厚但圓、人聲貼耳又滑順、高音不尖，聲音在前方像聽喇叭。適合 R&B、靈魂、新靈魂、Bruno Mars",
    "後朋克／冷波": "Corn Wave、Joy Division、The Cure、Interpol：貝斯圓、人聲浮出來、吉他冷而亮、空氣感足。適合獨立後朋克、冷波、空靈搖滾",
}
# 「你的歌單」分頁在啟動時依這台電腦的 Tidal 收藏產生（analyze_tidal），有才會出現
STYLE_GROUPS = [("推薦", RESEARCH), ("曲風", GENRE), ("搖滾", ROCK), ("空間感", STAGE), ("旗艦耳機", LEGEND), ("熱門耳機", POPULAR), ("平價耳機", CHEAP)]
STYLES = [s for _name, group in STYLE_GROUPS for s in group]
FREQS = [20 * 1000 ** (i / 199) for i in range(200)]
AUTO = "自動 "  # 自動存檔的預設名稱開頭
# 固定預留的音量空間（dB）：不管切換哪個設定、開關 EQ，音量都一樣，方便比較音質。
# 依選的耳機自動算（update_headroom）：＝這支耳機的各種校正＋所有內建風格裡最大的加強
HEADROOM = 11.0
# 耳機交叉饋送（bs2b 三組標準參數）：名稱, 低頻側訊號衰減 dB, 轉折頻率 Hz
# 輕＝Jan Meier（650 Hz / 9.5 dB）、中＝Chu Moy（700 Hz / 6 dB）、強＝bs2b 預設（700 Hz / 4.5 dB）
# 現在只取它們的低頻分離度（9.6／6.0／4.5 dB），頻率響應和時間差改用頭部模型精確計算（xfeed_tf）；沒有 numpy 時才用這裡的中/側濾波
CROSSFEED = [("關", 0.0, 700), ("輕", -6.0, 650), ("中", -9.6, 700), ("強", -11.9, 700), ("喇叭", -11.9, 700)]
# 殘響空間：名稱, 中頻殘響 RT60(秒), 低頻比, 高頻比, 首次反射 ITDG(ms), 直達/殘響比 DRR(dB), 檔名
ROOMS = [("關", 0, 0, 0, 0, 0, ""),
         ("錄音室", 0.25, 1.0, 0.9, 3, 10, "studio"),         # ITU-R BS.1116 標準聆聽室
         ("音樂廳前排", 2.0, 1.2, 0.75, 15, 6, "hall_front"),  # Beranek 頂級音樂廳（維也納金色大廳約 2.0 秒）
         ("音樂廳中段", 2.0, 1.2, 0.75, 20, 3, "hall_mid")]    # 往後坐：直達/殘響比少 3 dB（約遠 1.4 倍，Zahorik 2002）


REVERB_RATES = (44100, 48000, 88200, 96000, 176400, 192000)  # 這些取樣率都先做好殘響檔（調音台沒開時裝置換取樣率也有殘響）


# 殘響 v5：tools/殘響模擬.py 用顯示卡在真實形狀的房間裡做聲學模擬（鏡像聲源的早期反射＋每個聲源 3,355 萬條聲線追蹤的後段
# ＋剛性球頭部模型），存在「殘響」資料夾；殘響時間照 ROOMS，直達/殘響比在這裡縮放。
# 沒有那個檔（或讀不了）就用 room_ir 裡的簡化版（v3，itdg 只在那裡用）
REVERB_DIR = os.path.join(APP_DIR, "殘響")
MASTER_FS = 96000  # 模擬檔的取樣率（跟 tools/殘響模擬.py 算的一樣，不另外轉）
_MASTERS = {}


HEAD_USE = ["KU100"]  # 頭型（「交叉饋送」底下的「頭型 ▾」）：KU100 假人頭＝主要那份，其他是 SADIE II 真人另算的一組


def head_file(name):
    """選了真人頭型時，那個人算好的檔（殘響/頭部/<代號>/）優先，沒有的（例：音樂廳）用主要那份 → (路徑, 檔名標記)"""
    if HEAD_USE[0] != "KU100":
        p = os.path.join(REVERB_DIR, "頭部", HEAD_USE[0], name)
        if os.path.exists(p):
            return p, HEAD_USE[0].lower()
    return os.path.join(REVERB_DIR, name), ""


def room_master(key):
    """這個房間模擬好的殘響（96 kHz、4 聲道、只有殘響、每個聲源兩耳總能量＝1）→ (陣列, 版本) 或 None"""
    path, who = head_file(f"{key}.npy")
    try:
        tag = f"{int(os.path.getmtime(path)) % 65536:04x}{who}"  # 模擬檔更新過、換頭型 → 檔名跟著換，Equalizer APO 才會讀新的
    except OSError:
        return None
    if _MASTERS.get(key, (None, None))[1] != tag:
        try:
            import numpy as np
            _MASTERS[key] = (np.load(path).astype(float), tag)  # 每個房間只留現在頭型的那份
        except (ImportError, OSError, ValueError):
            return None
    return _MASTERS[key]


def _resample(x, rate, src=MASTER_FS):
    """FFT 轉取樣率（模擬檔 20 kHz 以上已經濾掉，不會疊頻）；脈衝響應要保持同樣的頻率響應 → 不再乘長度比例"""
    import numpy as np
    if rate == src:
        return x.copy()
    m = int(round(len(x) * rate / src))
    X = np.fft.rfft(x, axis=0)
    k = min(m // 2 + 1, len(X))
    Y = np.zeros((m // 2 + 1, x.shape[1]), complex)
    Y[:k] = X[:k]
    return np.fft.irfft(Y, m, axis=0)


def write_wav(path, data, rate):
    """32-bit 浮點 WAV（Equalizer APO 的摺積用）；先寫暫存檔再改名，Equalizer APO 不會讀到寫一半的檔"""
    raw = data.astype("<f4").tobytes()
    ch = data.shape[1]
    head = (b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 3, ch, rate, rate * 4 * ch, 4 * ch, 32) + b"data" + struct.pack("<I", len(raw)))
    with open(path + ".tmp", "wb") as fh:
        fh.write(head + raw)
    os.replace(path + ".tmp", path)


SOUND_C, HEAD_A = 343.2, 0.0875  # 音速（20 °C）、頭的半徑


def sphere(f, theta, a=HEAD_A):
    """剛性球（半徑 a）表面一點，平面波從 theta 角來（0＝正對）的頻率響應：Duda & Martens 1998（JASA）的級數解；
    numpy 的時間慣例（延遲＝e^{-j2πfτ}）。跟 tools/殘響模擬.py 用的是同一個頭部模型"""
    import numpy as np
    f = np.asarray(f, float)
    H = np.ones((len(theta), len(f)), complex)
    x = 2 * np.pi * f * a / SOUND_C
    nz = x > 1e-6
    x = x[nz]
    M = int(x.max() + 10 * x.max() ** (1 / 3) + 20)
    j, y = np.zeros((M + 2, len(x))), np.zeros((M + 2, len(x)))
    j[0], j[1] = np.sin(x) / x, np.sin(x) / x ** 2 - np.cos(x) / x
    y[0], y[1] = -np.cos(x) / x, -np.cos(x) / x ** 2 - np.sin(x) / x
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        for m in range(1, M + 1):
            j[m + 1] = (2 * m + 1) / x * j[m] - j[m - 1]
            y[m + 1] = (2 * m + 1) / x * y[m] - y[m - 1]
        h = j + 1j * y
        dh = np.empty((M + 1, len(x)), complex)
        dh[0] = -h[1]
        mm = np.arange(M + 1)[:, None]
        dh[1:] = h[:-2] - (mm[1:] + 1) / x * h[1:-1]
        use = (mm <= x + 10 * x ** (1 / 3) + 20) & np.isfinite(dh) & (np.abs(dh) > 0)
        coef = np.where(use, (-1j) ** (mm - 1.0) * (2 * mm + 1) / np.where(use, dh, 1), 0)
    c = np.cos(theta)
    P = np.zeros((len(theta), M + 1))
    P[:, 0] = 1
    P[:, 1] = c
    for m in range(1, M):
        P[:, m + 1] = ((2 * m + 1) * c * P[:, m] - m * P[:, m - 1]) / (m + 1)
    H[:, nz] = (P @ coef) / x ** 2
    return np.conj(H)


def minphase(mag):
    """大小 → 最小相位的頻率響應（倒頻譜法）"""
    import numpy as np
    n = 2 * (len(mag) - 1)
    c = np.fft.irfft(np.log(np.maximum(mag, 1e-8)), n)
    c[1:n // 2] *= 2
    c[n // 2 + 1:] = 0
    return np.exp(np.fft.rfft(c, n))


# 交叉饋送 v2：喇叭在 ±30°（ITU-R BS.775）時，左喇叭的聲音會繞過頭到右耳——Bauer 1961 交叉饋送的原意。
# 用剛性球頭的精確解算出「對側耳／同側耳」的兩耳傳遞函數（時間差約 0.26 ms、頻率越高被頭擋掉越多），
# 取代原本只把低頻左右混一點、沒有時間差的中/側濾波。輕／中／強 照原本的低頻左右分離度（9.6／6.0／4.5 dB），
# 再補償成「左右一樣的聲音（人聲、貝斯）總響應平直」→ 音色不變，只有左右分很開的聲音被拉回前方
XF_EAR, XF_SPK = 100, 30  # 耳朵在正前方左右 100°、喇叭在 ±30°
_XF, _ITF = {}, {}
# v3：有真人頭部量測（SADIE II 資料庫的 Neumann KU100 假人頭，University of York，Apache 2.0；殘響/hrtf30.npy＝
# 左前 30° 喇叭到同側耳、對側耳）就用量測的兩耳傳遞函數（有耳廓，比球形頭準），沒有才用剛性球模型；
# 選了真人頭型就用那個人的（殘響/頭部/<代號>/hrtf30.npy）


def measured_itf():
    """量測的兩耳傳遞函數（對側／同側）→ (96 kHz 脈衝響應, 往前挪的取樣數) 或 None"""
    path = head_file("hrtf30.npy")[0]
    if path not in _ITF:
        try:
            import numpy as np
            hi, hc = np.load(path).astype(float)
            n, pre, keep = 1 << 14, 64, 512
            Hi, Hc = np.fft.rfft(hi, n), np.fft.rfft(hc, n)
            itf = Hc * np.conj(Hi) / (np.abs(Hi) ** 2 + 1e-3 * (np.abs(Hi) ** 2).max())  # 同側有凹陷的地方不會爆掉
            ir = np.roll(np.fft.irfft(itf, n), pre)[:keep]
            ir[:16] *= np.sin(np.linspace(0, np.pi / 2, 16)) ** 2
            ir[-64:] *= np.cos(np.linspace(0, np.pi / 2, 64)) ** 2
            _ITF[path] = (ir, pre)
        except (ImportError, OSError, ValueError):
            _ITF[path] = None
    return _ITF[path]


def xfeed_tf(level, f):
    """交叉饋送的頻率響應 → (同側, 對側)；f 是 rfft 的頻率格"""
    key = (level, len(f), float(f[-1]), head_file("hrtf30.npy")[0])
    if key not in _XF:
        import numpy as np
        g = 10 ** (CROSSFEED[level][1] / 20)
        c = (1 - g) / (1 + g)  # 低頻的對側量：跟原本的中/側濾波低頻分離度一樣
        m = measured_itf()
        if m:
            ir, pre = m
            itf = np.exp(-2j * np.pi * np.outer(f, np.arange(len(ir)) - pre) / 96000) @ ir
            itf *= np.clip((20000 - f) / 2000, 0, 1) ** 2  # 量測只到 20 kHz，以上不串音
            # 量測在 100 Hz 也有約 1.4 dB 的兩耳差 → 對側量照比例放大，低頻左右分離度才會跟原本一樣
            c /= abs(np.exp(-2j * np.pi * 100 * (np.arange(len(ir)) - pre) / 96000) @ ir)
        else:
            H = sphere(f, np.radians([XF_EAR - XF_SPK, XF_EAR + XF_SPK]))
            itf = H[1] / H[0]
        eq = minphase(1 / np.abs(1 + c * itf))  # 左右一樣的聲音：同側＋對側剛好平直
        _XF[key] = (eq, eq * c * itf)
    return _XF[key]


def xfeed_files(cfg_dir, level):
    """每個取樣率一份交叉饋送檔（4 聲道：L、R 的同側，XL、XR 的對側）→ {取樣率: 檔名}"""
    import numpy as np
    out = {}
    ver = "v3" + head_file("hrtf30.npy")[1] if measured_itf() else "v2"  # 換頭型 → 換檔名
    for rate in RATES:
        name = f"xfeed_{ver}_{level}_{rate}.wav"
        path = os.path.join(cfg_dir, name)
        if not os.path.exists(path):
            n = 1 << max(10, math.ceil(math.log2(rate * 0.04)))
            same, cross = xfeed_tf(level, np.fft.rfftfreq(n, 1 / rate))
            hs, hx = np.fft.irfft(same, n), np.fft.irfft(cross, n)
            fade = np.ones(n)
            fade[n // 2:] = np.cos(np.linspace(0, np.pi / 2, n - n // 2)) ** 2
            write_wav(path, np.stack([hs, hs, hx, hx], 1) * fade[:, None], rate)
        out[rate] = name
    return out


# 虛擬喇叭（交叉饋送最右邊一格「喇叭」）：tools/殘響模擬.py 在 BS.1116 標準聆聽室裡擺一對 ±30° 的喇叭，
# 算出兩顆喇叭到兩耳的直達聲（經過頭部量測）＋每一道反射（殘響\studio_spk.npy），4 聲道跟交叉饋送檔一樣
SPEAKER = 4
_SPK = {}


def smooth_third(mag):
    """1/3 八度平滑（能量平均），mag 是 rfft 頻率格上的大小"""
    import numpy as np
    cs = np.concatenate([[0], np.cumsum(mag ** 2)])
    i = np.arange(len(mag))
    lo = np.floor(i / 2 ** (1 / 6)).astype(int)
    hi = np.minimum(np.ceil(i * 2 ** (1 / 6)).astype(int) + 1, len(mag))
    return np.sqrt((cs[hi] - cs[lo]) / np.maximum(hi - lo, 1))


def speaker_ir(rate):
    """虛擬喇叭（4 聲道：左→左、右→右、左→右、右→左）。補償成「左右一樣的聲音」總響應平直
    （1/3 八度平滑，最多 ±12 dB）→ 人聲音色不變，只有方向和空間感改變 → (陣列, 版本) 或 None"""
    master = room_master("studio_spk")
    if master is None:
        return None
    key = (rate, master[1])
    if key not in _SPK:
        import numpy as np
        x = _resample(master[0], rate)
        m = len(x) + rate // 50
        n = 1 << (2 * m - 1).bit_length()
        X = np.fft.rfft(x, n, axis=0)
        f = np.fft.rfftfreq(n, 1 / rate)
        mono = np.sqrt((np.abs(X[:, 0] + X[:, 3]) ** 2 + np.abs(X[:, 1] + X[:, 2]) ** 2) / 2)
        inv = 1 / np.maximum(smooth_third(mono), 1e-9)
        lo, hi = np.searchsorted(f, 20), np.searchsorted(f, 20000)
        inv[:lo], inv[hi:] = inv[lo], inv[hi - 1]  # 20 Hz–20 kHz 以外不另外補
        y = np.fft.irfft(X * minphase(np.clip(inv, 0.25, 4))[:, None], n, axis=0)[:m]
        y[-rate // 100:] *= np.cos(np.linspace(0, np.pi / 2, rate // 100))[:, None] ** 2
        _SPK.clear()
        _SPK[key] = y
    return _SPK[key], master[1]


def spk_files(cfg_dir):
    """每個取樣率一份虛擬喇叭檔 → {取樣率: 檔名}；沒有模擬檔 → {}"""
    out = {}
    tag = room_master("studio_spk")
    if tag is None:
        return out
    for rate in RATES:
        name = f"spk_v1{tag[1]}_{rate}.wav"
        if not os.path.exists(os.path.join(cfg_dir, name)):
            write_wav(os.path.join(cfg_dir, name), speaker_ir(rate)[0], rate)
        out[rate] = name
    return out


# 分離度：Equalizer APO 直接載入的 VST 外掛（分離度引擎\sep_v1.dll，原始碼 sep.cpp，MIT）。每個頻率（約 21 ms 的
# 短時傅立葉）把左右分成「主要的聲音」和環境音，靠中間的樂器往兩邊拉開、加上對應的兩耳時間差（只在 2 kHz 以下）；
# 人聲、正中間和最左右的不動，環境音、殘響不動。第 2 版：位置估計在頻率方向平均約半個聽覺頻帶、時間 50 ms
# → 推的量不再一格一格跳（第 1 版的顆粒感）。延遲約 23 ms；強度 0 跟原音逐位元一樣
SEP_DLL = os.path.join(APP_DIR, "分離度引擎", "sep_v1.dll")
SEP_LEVELS = [("關", 0.0), ("輕", 0.35), ("中", 0.6), ("強", 0.9)]
SEP_MARGIN = 1.0  # 拉開時峰值最多多約 0.2 dB，多留一點


def sep_file(cfg_dir):
    """把外掛複製到 Equalizer APO 的設定資料夾（音訊服務讀得到）；檔名帶內容雜湊 → 更新時不會撞到正在用的舊檔"""
    try:
        with open(SEP_DLL, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    name = f"sep_{zlib.crc32(data):08x}.dll"
    path = os.path.join(cfg_dir, name)
    if not os.path.exists(path):
        with open(path + ".tmp", "wb") as fh:
            fh.write(data)
        os.replace(path + ".tmp", path)
    return name


def sep_lines(cfg_dir, name, strength):
    chunk = base64.b64encode(f"strength={strength:.3f}".encode()).decode()
    return [f'VSTPlugin: Library "{os.path.join(cfg_dir, name)}" ChunkData "{chunk}"']


def xfeed_lines(files):
    out = []
    for rate, name in sorted(files.items()):
        out += [f"If: sampleRate == {rate}", "Copy: XL=L XR=R", "Channel: L R XL XR", f"Convolution: {name}",
                "Channel: all", "Copy: L=L+XR R=R+XL", "EndIf:"]
    return out


# 電腦重建濾波：裝置設成 88.2 kHz 以上時，在電腦裡用長的線性相位濾波器把 20 kHz 以上濾乾淨
# （通帶到 20 kHz、22.05 kHz 起阻隔 140 dB，Kaiser 窗；32-bit 浮點的極限附近）。串流和 CD 多半是 44.1 kHz：
# Windows 轉取樣率留下的鏡像、處理產生的超音波都在這裡清掉，DAC 自己的數位濾波器只剩輕鬆的工作
# ——也就是把重建濾波的「解析力負擔」交給電腦（HQPlayer 這類軟體的作法）。延遲約 2 ms
RECON_MIN = 88200
RECON_PASS, RECON_STOP, RECON_DB = 20000.0, 22050.0, 140.0
_LP = {}


def recon_taps(rate):
    import numpy as np
    beta = 0.1102 * (RECON_DB - 8.7)
    n = int(math.ceil((RECON_DB - 7.95) / (14.36 * (RECON_STOP - RECON_PASS) / rate))) | 1
    t = np.arange(n) - (n - 1) / 2
    fc = (RECON_PASS + RECON_STOP) / 2 / rate
    h = 2 * fc * np.sinc(2 * fc * t) * np.kaiser(n, beta)
    return h / h.sum()


def recon_files(cfg_dir):
    import numpy as np
    out = {}
    for rate in RATES:
        if rate >= RECON_MIN:
            name = f"recon_v1_{rate}.wav"
            if not os.path.exists(os.path.join(cfg_dir, name)):
                h = recon_taps(rate)
                write_wav(os.path.join(cfg_dir, name), np.stack([h, h], 1), rate)
            out[rate] = name
    return out


def recon_lines(files):
    out = []
    for rate, name in sorted(files.items()):
        out += [f"If: sampleRate == {rate}", "Channel: L R", f"Convolution: {name}", "Channel: all", "EndIf:"]
    return out


def recon_lp(f):
    """重建濾波的大小（算峰值用；線性相位，延遲不影響峰值）"""
    key = (len(f), float(f[-1]))
    if key not in _LP:
        import numpy as np
        rate = 352800
        n = 1 << 21
        H = np.abs(np.fft.rfft(recon_taps(rate), n))
        _LP[key] = np.interp(f, np.fft.rfftfreq(n, 1 / rate), H)
    return _LP[key]


def room_ir(room, rate):
    """殘響的脈衝響應，4 聲道：0＝左→左、1＝右→右、2＝左→右、3＝右→左。
    真實房間裡，左邊樂器的殘響兩耳都聽得到（擴散聲場兩耳能量相同），所以每個聲源各有一對兩耳的尾巴；
    兩耳相關性照真實擴散聲場 sin(kd)/kd（Lindevald & Benade，耳距約 18 cm）→ 低頻兩耳幾乎一樣、約 1 kHz 以上各自獨立。
    每條尾巴能量各一半 → 置中的聲音直達/殘響比跟設定一樣，偏一邊的聲音殘響也不會只出現在同一耳"""
    import numpy as np
    _n, rt, br, tr, itdg, drr, key = ROOMS[room]
    master = room_master(key)
    if master is not None:  # v5：模擬好的房間，依直達/殘響比縮放
        # 直達/殘響比用 20 Hz–20 kHz 裡的能量算：模擬檔只到 20 kHz，原音的單位脈衝只有一部分能量在這範圍
        # → 任何取樣率聽起來都一樣大（舊版 v3 在不同取樣率會差 2–3 dB）
        ir = _resample(master[0], rate) * 10 ** (-drr / 20) * math.sqrt(20000 / (MASTER_FS / 2))
        ir[0, :2] += 1.0  # 直達聲＝原音
        return ir
    n = int(rate * (itdg / 1000 + rt * max(br, 1) * 1.05))
    t = np.arange(n) / rate
    freqs = np.fft.rfftfreq(n, 1 / rate)
    rng = np.random.default_rng(7)  # 固定種子：每次做出來都一樣
    start = int(rate * itdg / 1000)
    coh = np.clip(np.sinc(2 * freqs * 0.18 / 343), 0, 1)
    # 殘響慢慢長出來（不是一開始就滿），避免跟原音疊出梳狀的顆粒感
    onset = 1 - np.exp(-np.maximum(t - itdg / 1000, 0) / max(rt * 0.01, 0.002))
    ir = np.zeros((n, 4))
    for src in (0, 1):  # 左邊的聲源、右邊的聲源
        common, ipsi, contra = (np.fft.rfft(rng.standard_normal(n)) for _ in range(3))
        for ch, own in ((src, ipsi), (2 + src, contra)):
            spec = np.sqrt(coh) * common + np.sqrt(1 - coh) * own
            tail = np.zeros(n)
            # 各頻段衰減速度不同；8 kHz 以上再快一點（空氣吸收，ISO 9613-1），殘響尾巴才不會沙沙的
            for lo, hi, r in ((0, 500, rt * br), (500, 4000, rt), (4000, 8000, rt * tr), (8000, rate, rt * tr * 0.6)):
                tail += np.fft.irfft(np.where((freqs >= lo) & (freqs < hi), spec, 0), n) * np.exp(-6.91 * t / r)
            tail *= onset
            tail[:start] = 0
            tail *= math.sqrt(0.5 * 10 ** (-drr / 10) / (tail ** 2).sum())  # 依直達/殘響比調整殘響大小
            ir[:, ch] = tail
    ir[0, :2] += 1.0  # 直達聲＝原音
    return ir


def room_name(room, rate):
    master = room_master(ROOMS[room][6])
    ver = f"v5{master[1]}" if master else "v3"  # v3：左右兩耳都有殘響；v5：模擬的房間
    return f"reverb_{ROOMS[room][6]}_{ver}_{rate}.wav"


def room_file(cfg_dir, room, rate):
    """殘響檔（Equalizer APO 不會自動轉取樣率，所以每個取樣率各一份）；已經有就直接用"""
    name = room_name(room, rate)
    path = os.path.join(cfg_dir, name)
    if not os.path.exists(path):
        write_wav(path, room_ir(room, rate), rate)
    return name


def write_atomic(path, text):
    """先寫暫存檔再整個換掉：Equalizer APO 隨時可能讀，直接覆寫的話可能讀到空的或寫一半的設定
    （那一瞬間沒有降音量、沒有 EQ → 爆一聲大聲）"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii") as fh:
        fh.write(text)
    for _ in range(25):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Equalizer APO 剛好開著那個檔：等一下再換
            time.sleep(0.02)
    with open(path, "w", encoding="ascii") as fh:  # 一直換不掉才直接寫
        fh.write(text)
    os.remove(tmp)


def cleanup_reverb(cfg_dir, keep):
    """刪掉用不到的殘響檔（Equalizer APO 還開著的刪不掉，下次再刪；背景正在寫的暫存檔不動）"""
    for fn in os.listdir(cfg_dir):
        if fn.endswith(".tmp") and time.time() - os.path.getmtime(os.path.join(cfg_dir, fn)) < 600:
            continue
        spk = room_master("studio_spk")
        old_spk = fn.startswith("spk_") and fn not in keep and not (spk and fn.startswith(f"spk_v1{spk[1]}_"))
        old_sep = fn.startswith("sep_") and fn.endswith(".dll") and fn not in keep  # 舊版外掛（還在用的刪不掉，下次再刪）
        old_xf = fn.startswith("xfeed_v3") and fn not in keep  # 換頭型前的交叉饋送檔（要用時會再做）
        if (fn.startswith("reverb_") and fn not in keep) or old_spk or old_sep or old_xf:
            try:
                os.remove(os.path.join(cfg_dir, fn))
            except OSError:
                pass


def reverb_lines(files):
    """files＝{取樣率: 殘響檔}。每個取樣率包在 If 裡：Equalizer APO 不會轉殘響檔的取樣率（對不上會整段跳過），
    沒有對應檔案的取樣率就完全不動（不能只做一半，不然原音會被加到對面聲道）。
    RVL／RVR 是原音的複本（虛擬聲道），做完摺積才加到對面聲道 → 左邊的聲音右耳也有殘響"""
    out = []
    for rate, name in sorted(files.items()):
        out += [f"If: sampleRate == {rate}", "Copy: RVL=L RVR=R", "Channel: L R RVL RVR", f"Convolution: {name}",
                "Channel: all", "Copy: L=L+RVR R=R+RVL", "EndIf:"]
    return out


# ---------------------------------------------------------------- 防破音：實際算輸出峰值
# 只看穩態頻率響應（某個頻率最多加強多少）會低估：EQ 會改變各頻率的相位，滿格母帶的波峰會疊得更高
# （用 Equalizer APO 實測：比穩態估計多 0.9 dB（中位數）、95% 在 2.1 dB 內、最多 2.9 dB）；
# 聲場寬度在左右反相時加強 1+2k 倍，不是 1+k。→ 用幾種「滿格母帶」測試訊號實際算一次目前設定的輸出峰值
SAFETY = 0.5     # 再多留 0.5 dB：測試訊號以外的歌、DAC 內部超取樣（樣本之間的波峰）
OVERSHOOT = 2.0  # 固定預留用：穩態估計再加 2 dB（實測 95% 的組合夠；不夠的那組會自動再多降）
_SIGNALS, _PEAKS, _IRS = [], {}, {}


def _test_signals(np):
    if not _SIGNALS:
        rng, n = np.random.default_rng(11), 72000  # 48 kHz、1.5 秒
        f = np.fft.rfftfreq(n, 1 / 48000)

        def pink():
            spec = np.fft.rfft(rng.standard_normal(n))
            p = np.fft.irfft(spec / np.sqrt(np.maximum(np.arange(len(spec)), 1)), n)
            return p / np.abs(p).max()

        def low(x, fc):
            y = np.fft.irfft(np.fft.rfft(x) / (1 + (f / fc) ** 2), n)
            return y / np.abs(y).max()

        for _ in range(2):  # 兩組獨立的：左右是不同樂器時用
            p1, p2 = pink(), pink()
            sigs = [np.tanh(p1 * 6), np.clip(p1 * 4, -1, 1), np.tanh(low(p1, 120) * 4), np.clip(low(p2, 80) * 3, -1, 1)]
            _SIGNALS.append([s / np.abs(s).max() for s in sigs])
    return _SIGNALS


def _H(np, filters, f, fs=48000.0):
    """濾波器串聯的複數頻率響應（跟 Equalizer APO 同一套公式；增益、Q 照設定檔的位數取整）"""
    H = np.ones(len(f), dtype=complex)
    z = np.exp(-2j * np.pi * f / fs)
    for kind, fc, gain, q in filters:
        gain, q = round(gain, 1), round(q, 2)
        if not gain:
            continue
        A = 10 ** (gain / 40)
        w0 = 2 * math.pi * fc / fs
        c, al = math.cos(w0), math.sin(w0) / (2 * q)
        if kind == "PK":
            b, a = (1 + al * A, -2 * c, 1 - al * A), (1 + al / A, -2 * c, 1 - al / A)
        else:
            sq = 2 * math.sqrt(A) * al
            if kind == "LSC":
                b = (A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq))
                a = ((A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq)
            else:
                b = (A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq))
                a = ((A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq)
        H *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return H


def steady_peak(filters, width=0):
    """穩態最大加強（dB）：寬度取左右反相時的最壞情況 1+2k（交叉饋送只讓左右互滲，不會加強）"""
    return max(curve(filters) or [0.0]) + 20 * math.log10(1 + 2 * width / 100)


def true_peak(filters, width=0, crossfeed=0, room=0, recon=False):
    """滿格母帶經過這組設定後的輸出峰值（dB，0＝跟輸入滿格一樣大）。
    recon＝電腦重建濾波開著：濾掉 20 kHz 以上後，削波母帶的波峰會冒出來（樣本之間的峰值）→ 用 4 倍超取樣算"""
    key = (tuple(filters), width, crossfeed, room, recon)
    if key in _PEAKS:
        return _PEAKS[key]
    try:
        import numpy as np
    except ImportError:  # 沒有 numpy：用穩態估計＋實測最多的暫態超出量
        return steady_peak(filters, width) + 3.0
    sigs = _test_signals(np)
    if room and room not in _IRS:
        _IRS[room] = room_ir(room, 48000)  # 算峰值用的 48 kHz 殘響
    ir = _IRS[room] if room else None
    spk = speaker_ir(48000) if crossfeed == SPEAKER else None
    n = len(sigs[0][0]) + (len(ir) if ir is not None else 0) + (len(spk[0]) if spk else 0) + 24000
    nfft = 1 << (n - 1).bit_length()
    f = np.fft.rfftfreq(nfft, 1 / 48000)
    he = _H(np, filters, f)
    k = width / 100
    a, b = xfeed_tf(crossfeed, f) if crossfeed and not spk else (1, 0)  # 交叉饋送：同側、對側
    lp = recon_lp(f) if recon else None
    ll, lr = he * ((1 + k) * a - k * b), he * ((1 + k) * b - k * a)  # 再加上寬度
    if ir is not None:
        r = np.fft.rfft(ir, nfft, axis=0)
    if spk:
        sp = np.fft.rfft(spk[0], nfft, axis=0)
    peak = 0.0
    for s1, s2 in zip(*sigs):
        X1, X2 = np.fft.rfft(s1, nfft), np.fft.rfft(s2, nfft)
        for xl, xr in ((X1, X1), (X1, -X1), (X1, X2)):  # 左右相同、左右反相、左右不同樂器
            if spk:  # 虛擬喇叭（4 聲道）在寬度之前
                xl, xr = sp[:, 0] * xl + sp[:, 3] * xr, sp[:, 1] * xr + sp[:, 2] * xl
            yl, yr = ll * xl + lr * xr, lr * xl + ll * xr
            if ir is not None:
                yl, yr = r[:, 0] * yl + r[:, 3] * yr, r[:, 1] * yr + r[:, 2] * yl
            if lp is not None:
                m = 4 * nfft
                peak = max(peak, 4 * np.abs(np.fft.irfft(yl * lp, m)).max(), 4 * np.abs(np.fft.irfft(yr * lp, m)).max())
            else:
                peak = max(peak, np.abs(np.fft.irfft(yl, nfft)).max(), np.abs(np.fft.irfft(yr, nfft)).max())
    if len(_PEAKS) > 300:
        _PEAKS.clear()
    _PEAKS[key] = 20 * math.log10(peak)
    return _PEAKS[key]


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
            try:
                with winreg.OpenKey(root, guid + r"\Properties") as p:
                    enum = str(winreg.QueryValueEx(p, ENUM_KEY)[0]).upper()
            except OSError:
                enum = ""
            bt = (("handsfree" if enum.startswith("BTHHF") or "HANDS-FREE" in iface.upper() else "stereo")
                  if enum.startswith("BTH") else None)
            out.append({"guid": guid, "name": f"{desc} ({iface})" if desc else iface, "iface": iface, "desc": desc,
                        "active": active, "hooked": hooked, "fmt": fmt, "bt": bt})
    return out


def work_area():
    """螢幕扣掉工作列的大小（實際像素）"""
    r = ctypes.wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
        return r.right - r.left, r.bottom - r.top
    return None


def default_device_guid(strict=False):
    """Windows 目前的預設輸出裝置（strict＝讀不到就回傳 None，不用猜的）"""
    try:
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetSpeakers().id.rsplit(".", 1)[-1]
    except Exception:
        if strict:
            return None
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
    i = next((k for k, ln in enumerate(lines) if ln.startswith(ORIG_MARK)), -1)
    if i >= 0:  # 調音台加的「只套用其他裝置」拿掉 → 原本的設定恢復成套用全部
        del lines[i:i + (2 if i + 1 < len(lines) and lines[i + 1].lower().startswith("device:") else 1)]
    new_text = text[:text.index(BLOCK_BEGIN)] + "\n".join(lines)
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(new_text)
    for fn in os.listdir(cfg_dir):
        if fn.startswith("tuner_") and fn.endswith(".txt"):
            try:
                os.remove(os.path.join(cfg_dir, fn))
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


def ensure_config(cfg_dir, devs, all_guids):
    """config.txt 開頭放調音台的區塊：每個用過的裝置各一段，Include 它自己的設定檔
    （藍牙耳機連上時 Equalizer APO 自動用它那段，調音台沒開也一樣）。
    原本的設定改成只套用在其他裝置（區段寫了這些裝置的代號、名稱或 all 的，把它們排除），
    才不會在同一個裝置上疊兩次。第一次改之前會先備份。回傳 True＝有改動"""
    path = os.path.join(cfg_dir, "config.txt")
    text = read_text(path).replace("\r\n", "\n") if os.path.exists(path) else ""
    mine = {d["guid"].lower() for d in devs}
    others = [g for g in all_guids if g.lower() not in mine] or [DUMMY_GUID]
    names = [n.lower() for d in devs for n in (d["iface"], d["desc"], d["name"]) if n]
    if BLOCK_BEGIN in text and BLOCK_END in text:
        # 區塊前面如果有東西（例如其他調音程式後來加的）也要留著，不能直接丟掉
        b, e = text.index(BLOCK_BEGIN), text.index(BLOCK_END) + len(BLOCK_END)
        rest = (text[:b].rstrip("\n") + "\n" + text[e:].lstrip("\n")).lstrip("\n")
    else:
        backup = os.path.join(cfg_dir, "config_調音台之前的備份.txt")
        if text and not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(text)
        rest = text
    first = next((ln.strip() for ln in rest.splitlines() if ln.strip() and not ln.strip().startswith("#")), "")
    if first and not first.lower().startswith("device:"):  # 沒分裝置的設定＝套用全部 → 改成只套用其他裝置
        rest = ORIG_MARK + "\nDevice: " + "; ".join(others) + "\n" + rest
    lines = []
    for ln in rest.splitlines():
        st = ln.strip()
        if st.lower().startswith("device:"):
            pats = [p.strip() for p in st[7:].split(";") if p.strip()]
            new = []
            for p in pats:
                if p.lower() == "all":
                    new += others
                elif p.lower() in mine or any(p.lower() in n for n in names):
                    continue
                else:
                    new.append(p)
            if new != pats:
                ln = "Device: " + "; ".join(new or [DUMMY_GUID])
        lines.append(ln)
    block = BLOCK_BEGIN + "\n" + "".join(f"# {d['name']}\nDevice: {d['guid']}\nInclude: {out_name(d['guid'])}\n"
                                          for d in devs) + BLOCK_END + "\n"
    try:  # 舊版只有一個裝置時用的檔名
        os.remove(os.path.join(cfg_dir, "tuner_current.txt"))
    except OSError:
        pass
    new_text = block + "\n".join(lines) + ("\n" if lines else "")
    if new_text == text:
        return False
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(new_text)
    return True


def device_hit(pattern, dev):
    """Equalizer APO 的 Device: 規則：all，或裝置名稱／種類／代號裡包含這段文字（不分大小寫）"""
    p = pattern.strip().lower()
    return bool(p) and (p == "all" or any(p in n.lower() for n in (dev["guid"], dev["iface"], dev["desc"]) if n))


def config_problem(cfg_dir, dev):
    """照 Equalizer APO 的規則算「這個裝置實際會套用哪些設定」：
    其他程式改過 config.txt 時，可能變成沒套用調音台、或被調兩次，但 Windows 那邊看起來一切正常"""
    try:
        text = read_text(os.path.join(cfg_dir, "config.txt")).replace("\r\n", "\n")
    except OSError:
        return "讀不到 Equalizer APO 的設定檔"
    selected, ours, foreign = True, False, False  # 第一個 Device: 之前的指令套用到所有裝置
    for ln in text.split("\n"):
        st = ln.strip()
        if not st or st.startswith("#"):
            continue
        cmd, _sep, arg = st.partition(":")
        cmd = cmd.strip().lower()
        if cmd == "device":
            selected = any(device_hit(p, dev) for p in arg.split(";"))
        elif selected and cmd == "include" and arg.strip().lower() == out_name(dev["guid"]).lower():
            ours = True
        elif selected and cmd != "channel":
            foreign = True
    if not ours:
        return "設定檔被其他程式改過：這個裝置沒套用調音台"
    if foreign:
        return "設定檔被其他程式改過：這個裝置被調了兩次"
    return None


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
    out_dev = re.findall(r"Device id \[\s*\{[\d.]+\}\.(\{[0-9A-Fa-f-]+\})\s*\]", text)
    if out_dev:  # Tidal 實際輸出到哪個裝置
        info["dev"] = out_dev[-1].lower()
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
    """固定預留＝目前耳機的每一種校正 × 每個內建風格裡，最大的穩態加強＋暫態超出量（取 0.5 dB，6–20 dB 之間）。
    寬度用左右反相時的最壞情況 1+2k；個別組合還不夠的話，套用時會用實際峰值自動再多降"""
    global HEADROOM
    bases = [curve(fl) for _n, fl in BASES.values()]
    cache, worst = {}, 0.0
    for _n, vals, width, _cf, _src in STYLES:
        key = tuple(vals)
        if key not in cache:
            cache[key] = curve([(k, f, g, q) for (_b, k, f, q, _h), g in zip(BANDS, vals) if g])
        wk = 20 * math.log10(1 + 2 * width / 100)
        worst = max(worst, max(max(a + b for a, b in zip(bc, cache[key])) for bc in bases) + wk)
    HEADROOM = min(20.0, max(6.0, math.ceil((worst + OVERSHOOT) * 2) / 2))
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
    """有快取就用（Tidal 的快取檔沒變 → 結果一樣），開啟更快"""
    folder = os.path.join(os.environ.get("APPDATA", ""), "TIDAL", "Cache", "Cache_Data")
    try:
        files = [e for e in os.scandir(folder) if e.name.startswith("f_")]
        stamp = [len(files), max((e.stat().st_mtime for e in files), default=0)]
    except OSError:
        return [], {}
    path = os.path.join(APP_DIR, "歌單分析.json")
    try:
        with open(path, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("v") == 1 and c.get("stamp") == stamp:
            return [tuple(m) for m in c["mine"]], c["plain"]
    except (OSError, ValueError, KeyError):
        pass
    mine, plain = _analyze_tidal()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"v": 1, "stamp": stamp, "mine": mine, "plain": plain}, fh, ensure_ascii=False)
    except OSError:
        pass
    return mine, plain


def _analyze_tidal():
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


def k_weight_db(f, fs=48000.0):
    """ITU-R BS.1770 的 K 加權（響度量測標準用的耳朵權重）在頻率 f 的增益（dB）"""
    z = cmath.exp(-2j * math.pi * f / fs)
    h1 = (1.53512485958697 - 2.69169618940638 * z + 1.19839281085285 * z * z) / \
         (1 - 1.69065929318241 * z + 0.73248077421585 * z * z)
    h2 = (1 - 2 * z + z * z) / (1 - 1.99004745483398 * z + 0.99007225036621 * z * z)
    return 20 * math.log10(abs(h1 * h2))


_K_WEIGHT = []


def loudness_db(filters):
    """粉紅噪音經過這組濾波器後的響度（K 加權，dB，只拿來互相比較）"""
    if not _K_WEIGHT:
        _K_WEIGHT.extend(k_weight_db(f) for f in FREQS)
    return 10 * math.log10(sum(10 ** ((c + k) / 10) for c, k in zip(curve(filters), _K_WEIGHT)) / len(FREQS))


# ---------------------------------------------------------------- 多源共識
# 同一支耳機在 AutoEQ 裡常有好幾份量測（不同設備、不同單位）。每份都是「對自己設備的目標曲線差多少」（error_smoothed），
# 所以可以直接比：每個頻率跟其他份差越多的權重越低（某一份的假人頭耳廓不同時，高頻會被自動降權）；oratory1990 多一點權重
# （Harman 目標當初用的設備）；幾份不一致的地方只校正一部分；8 kHz 以上再平滑、限制幅度（量測最不可靠、每個人耳朵也差最多）
CONS_PRIOR = {"oratory1990": 1.5}


def _peq_resp(np, fl, f, fs):
    """參數等化的頻率響應（dB，不取整數，擬合用）"""
    H = np.ones(len(f), complex)
    z = np.exp(-2j * np.pi * f / fs)
    for kind, fc, g, q in fl:
        A = 10 ** (g / 40)
        w0 = 2 * np.pi * fc / fs
        c, al = np.cos(w0), np.sin(w0) / (2 * q)
        if kind == "PK":
            b, a = (1 + al * A, -2 * c, 1 - al * A), (1 + al / A, -2 * c, 1 - al / A)
        else:
            sq = 2 * np.sqrt(A) * al
            if kind == "LSC":
                b = (A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq))
                a = ((A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq)
            else:
                b = (A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq))
                a = ((A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq)
        H *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return 20 * np.log10(np.abs(H))


def fit_peq(np, F, T, n_pk=10, fs=48000.0):
    """把校正曲線 T（dB，頻率 F）擬合成低架 105 Hz＋高架 10 kHz＋n_pk 個峰值濾波器（Levenberg-Marquardt，
    一次加一個；增益越小越好 → 濾波器不會互相抵消）"""
    w = np.where(F <= 10000, 1.0, 0.5) * (F >= 20)

    def unpack(x, kinds):
        fl, i = [], 0
        for kind in kinds:
            if kind != "PK":
                fl.append((kind, 105.0 if kind == "LSC" else 10000.0, x[i], 0.7))
                i += 1
            else:
                fl.append(("PK", 2 ** x[i], x[i + 1], 2 ** x[i + 2]))
                i += 3
        return fl

    def clampx(x, kinds):
        i = 0
        for kind in kinds:
            if kind != "PK":
                x[i] = np.clip(x[i], -8, 8)
                i += 1
            else:
                x[i] = np.clip(x[i], np.log2(20), np.log2(16000))
                x[i + 1] = np.clip(x[i + 1], -9, 9)
                x[i + 2] = np.clip(x[i + 2], np.log2(0.2), np.log2(6))
                i += 3
        return x

    def res(x, kinds):
        fl = unpack(x, kinds)
        return np.concatenate([(_peq_resp(np, fl, F, fs) - T) * w, 0.6 * np.array([g for _k, _f, g, _q in fl])])

    def lm(x, kinds):
        lam, r = 1e-2, res(x, kinds)
        cost = (r ** 2).sum()
        for _ in range(40):
            J = np.stack([(res(x + e, kinds) - r) / 1e-4 for e in np.eye(len(x)) * 1e-4], 1)
            A, g = J.T @ J, J.T @ r
            while True:
                xn = clampx(x - np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), g), kinds)
                rn = res(xn, kinds)
                if (rn ** 2).sum() < cost:
                    x, r, cost, lam = xn, rn, (rn ** 2).sum(), lam / 3
                    break
                lam *= 4
                if lam > 1e8:
                    return x
        return x

    kinds = ["LSC", "HSC"]
    x = lm(np.zeros(2), kinds)
    for _ in range(n_pk):
        sm = np.convolve((T - _peq_resp(np, unpack(x, kinds), F, fs)) * w, np.ones(5) / 5, "same")
        i = int(np.argmax(np.abs(sm) * (F <= 16000)))
        kinds.append("PK")
        x = lm(np.append(x, [np.log2(F[i]), sm[i], np.log2(1.4)]), kinds)
    return [(k, int(round(fc)), round(float(g), 1), round(float(q), 2)) for k, fc, g, q in unpack(x, kinds)
            if abs(g) >= 0.1]


def consensus_fit(entries):
    """這支耳機所有量測 → 加權共識 → 參數等化 → [份數, 濾波器] 或 None（不到兩份、沒有 numpy、下載失敗）"""
    import csv
    import io as _io
    try:
        import numpy as np
    except ImportError:
        return None
    F = np.geomspace(20, 20000, 400)  # 每八度 40 點
    lf = np.log2(F)
    E, prior, seen = [], [], set()
    for src, link in entries:
        if link in seen or len(E) >= 8:
            continue
        seen.add(link)
        leaf = urllib.parse.unquote(link.rsplit("/", 1)[-1])
        try:
            with urllib.request.urlopen(AUTOEQ_RAW + link + "/" + urllib.parse.quote(leaf + ".csv"), timeout=30) as r:
                rows = list(csv.DictReader(_io.StringIO(r.read().decode("utf-8", "replace"))))
            f = np.array([float(x["frequency"]) for x in rows])
            e = np.array([float(x["error_smoothed"]) for x in rows])
        except Exception:
            continue
        E.append(np.interp(lf, np.log2(f), e))
        prior.append(CONS_PRIOR.get(src.split("（")[0], 1.0))
    if len(E) < 2:
        return None
    E = np.array(E)

    def smooth(X, oct_):
        return np.array([[row[np.abs(lf - lf[i]) <= oct_ / 2].mean() for i in range(len(F))] for row in X])
    R = np.array([E[s] - np.median(np.delete(E, s, 0), 0) for s in range(len(E))])  # 跟其他份的中位數差多少
    W = np.array(prior)[:, None] / (1.0 + smooth(R ** 2, 1 / 3))
    W /= W.sum(0)
    mean = (W * E).sum(0)
    se = np.sqrt((W * (E - mean) ** 2).sum(0) * (W ** 2).sum(0))  # 加權標準差 ÷ √有效份數
    corr = -mean / (1 + (se / 2.0) ** 2)  # 不確定的地方校正少一點
    x = np.clip((lf - np.log2(6000)) / (np.log2(8000) - np.log2(6000)), 0, 1)
    corr = corr * (1 - x) + smooth(corr[None], 0.5)[0] * x
    corr = np.where(F >= 10000, np.clip(corr, -6, 4), corr)
    return [len(E), [list(fl) for fl in fit_peq(np, F, corr)]]


# ---------------------------------------------------------------- 個人化：高頻校正、聲音偏好
# 高頻校正：3–10 kHz 的耳道共振、耳機跟耳朵的距離每個人都不一樣（個人差異可到 ±5 dB），量測用的假人頭抓不到。
# - 每題比相鄰兩個頻率（差 1/6 八度，音高很接近）：只比大小聲，誤差約 1 dB；跨好幾個八度比要 2–3 dB
# - 從 2.7 kHz 一格一格比到 12 kHz，再反方向比回來；兩個方向應該剛好相反，差多少就是這次測驗的誤差
# - 兩輪中間拿下耳機重戴：高頻會隨耳機在頭上的位置（入耳式是塞的深度）變好幾 dB → 重戴後還在的才是耳朵本身的峰谷
# - 只校正「跟平滑趨勢不一樣的窄峰窄谷」：整體高頻多寡是等響曲線加個人喜好（交給細調）；頭尾兩格只當起點終點
HF_BANDS = [round(3000 * 2 ** (i / 6)) for i in range(-1, 13)]  # 2.7–12 kHz，1/6 八度一格
HF_FREQS = HF_BANDS[1:-1]  # 會校正的：3–10.7 kHz
HF_Q = 4.3  # 頻寬約 1/3 八度：相鄰兩格重疊，接起來是平滑曲線


def hf_burst(np, fc, sr, sec=0.4):
    """以 fc 為中心、1/6 八度寬的噪音（邊緣用餘弦收尾），RMS＝1，前後 20 ms 淡入淡出"""
    n = int(sr * sec)
    f = np.fft.rfftfreq(n, 1 / sr)
    d = np.abs(np.log2(np.maximum(f, 1) / fc))
    mask = np.where(d <= 1 / 12, 1.0, np.cos(np.clip(d - 1 / 12, 0, 1 / 24) * 12 * np.pi) ** 2)
    x = np.fft.irfft(np.fft.rfft(np.random.default_rng().standard_normal(n)) * mask, n)
    x /= np.sqrt((x ** 2).mean())
    fade = np.minimum(1, np.minimum(np.arange(n), n - 1 - np.arange(n)) / (sr * 0.02))
    return x * fade


def hf_clip(np, ref, test, gain_db, level=0.06, sr=48000):
    """第一個聲音 → 0.15 秒空白 → 第二個聲音（加 gain_db）→ 0.5 秒空白，兩耳一樣；約 -24 dBFS"""
    gap = lambda s: np.zeros(int(sr * s))
    x = np.concatenate([ref, gap(0.15), test * 10 ** (gain_db / 20), gap(0.5)]) * level
    return np.column_stack([x, x]).astype("float32")


def hf_analyze(up, down):
    """up[j]：第 j+1 格要加幾 dB 才跟第 j 格一樣大聲；down[j]：第 j 格要加幾 dB 才跟第 j+1 格一樣大聲
    → (HF_FREQS 每個頻率的校正 dB, 濾波器, 每次判斷的誤差 dB)"""
    import numpy as np
    u, w = np.array(up, float), np.array(down, float)
    s = (u - w) / 2  # 相鄰兩格差多少（兩個方向平均）
    sig2 = max(((u + w) ** 2).mean() / 2, 0.25)  # 每次判斷的誤差（變異數），至少當 0.5 dB
    m = np.r_[0, np.cumsum(s)]  # 每一格要加幾 dB 才跟起點一樣大聲＝你的耳朵這裡比較小聲多少 → 補
    x = np.log2(np.array(HF_BANDS, float) / 1000)
    n = len(x)
    wt = np.ones(n)
    for _ in range(6):  # 平滑趨勢：偏離大的點權重降低，窄峰窄谷才不會被趨勢吃掉
        r = m - np.polyval(np.polyfit(x, m, 2, w=np.sqrt(wt)), x)
        wt = 1 / (1 + (r / 1.0) ** 2)
    K = np.zeros((n, n))  # 跟左右鄰居稍微平均：比 1/6 八度窄的抓不準
    for i in range(n):
        for j, c in ((i - 1, 0.1), (i, 0.8), (i + 1, 0.1)):
            K[i, j if 0 <= j < n else 2 * i - j] += c
    rs = K @ r
    # 每一格結果裡有多少是誤差：每次判斷的誤差一路累加（L）、扣掉趨勢（I−H）、再平滑（K）
    V = np.vander(x, 3)
    L = np.tril(np.ones((n, n - 1)), -1)
    P = K @ (np.eye(n) - V @ np.linalg.pinv(V)) @ L
    noise = sig2 / 2 * (P ** 2).sum(1)
    corr = np.clip(rs * rs ** 2 / (rs ** 2 + noise), -6, 6)[1:-1]  # 結果比誤差大越多越可信；差不多大的幾乎不校正
    fd = np.geomspace(1500, 20000, 240)
    xf = x[1:-1]
    target = np.interp(np.log2(fd / 1000), np.r_[xf[0] - 0.5, xf, xf[-1] + 0.5], np.r_[0, corr, 0])
    model = lambda g: 20 * np.log10(np.abs(_H(np, [("PK", fc, gi, HF_Q) for fc, gi in zip(HF_FREQS, g)], fd, 96000)))
    g, lam = corr.copy(), 0.15
    for _ in range(6):  # 高斯-牛頓，加一點懲罰：不要相鄰濾波器一正一負互相抵消
        base = model(g)
        J = np.stack([(model(g + e) - base) / 0.5 for e in np.eye(len(g)) * 0.5], 1)
        A = np.vstack([J, lam * np.eye(len(g))])
        g = np.clip(g + np.linalg.lstsq(A, np.r_[target - base, -lam * g], rcond=None)[0], -6, 6)
    filters = [("PK", fc, round(float(gi), 1), HF_Q) for fc, gi in zip(HF_FREQS, g) if abs(gi) >= 0.2]
    return [round(float(c), 1) for c in corr], filters, round(float(np.sqrt(sig2)), 1)


# 聲音偏好：Harman 的研究裡，同一個目標曲線最受歡迎，但每個人喜歡的低音、高音量不一樣（Olive, Acoustics Today 2022：
# 約 15% 偏好多 4–6 dB 低音、也有一群偏好少一點）→ 用你自己的歌盲聽比較，兩個方向各 8 題，差距由大到小（自適應）
PREF_STEPS = [3, 3, 2, 2, 1.5, 1.5, 1, 1]
PREF_RANGE = {"bass": (-6.0, 8.0), "treble": (-6.0, 6.0)}


def pref_filters(bass, treble):
    """跟細調的「低頻」「高頻」同一種濾波器（低架 105 Hz、高架 10 kHz）"""
    return [f for f in (("LSC", 105, round(bass, 1), 0.7), ("HSC", 10000, round(treble, 1), 0.7)) if f[2]]


# 頭型：KU100 假人頭＋SADIE II 資料庫的 18 位真人（University of York，Apache 2.0；左右對稱化），
# 每個人用 tools/殘響模擬.py 另外算好錄音室、虛擬喇叭、交叉饋送（殘響/頭部/<代號>/）；音樂廳用假人頭那份
HEADS_DIR = os.path.join(REVERB_DIR, "頭部")


def current_head():
    return HEAD_USE[0]


def head_sets():
    """可以切換的頭型：KU100＋有算好一組的（殘響/頭部/<代號>/studio_spk.npy）"""
    try:
        ids = [d for d in os.listdir(HEADS_DIR) if os.path.exists(os.path.join(HEADS_DIR, d, "studio_spk.npy"))]
    except OSError:
        ids = []
    return ["KU100"] + sorted(ids, key=lambda h: int(h[1:]) if h[1:].isdigit() else 0)


def head_name(hid):
    return "KU100 假人頭" if hid == "KU100" else f"真人 {hid}"


def head_groups_saved():
    """依前方的頻率響應＋兩耳時間差分好的組（殘響/頭部/分組.json，每組第一個是代表）；沒有就每個頭自己一組"""
    ids = head_sets()
    try:
        with open(os.path.join(HEADS_DIR, "分組.json"), encoding="utf-8") as fh:
            groups = [[h for h in g if h in ids] for g in json.load(fh)["groups"]]
        return [g for g in groups if g] + [[h] for h in ids if not any(h in g for g in groups)]
    except (OSError, ValueError, KeyError):
        return [[h] for h in ids]


RING_AZ = [30, 0, -30, 0]  # 頭型測驗：左前 30° → 正前 → 右前 30° → 正前（像前面擺了三個喇叭；左＝+）
RING_ON, RING_STEP, RING_PAUSE = 0.3, 0.45, 0.5  # 每個位置響 0.3 秒、0.45 秒換下一個；一輪停 0.5 秒再重來
_RING = {}


def head_ring(hid):
    """這個頭在前方三個方向的兩耳脈衝響應（殘響/頭部/前方.npz：左前 30°、正前、右前 30°，96 kHz）→ (4, 2, 取樣)"""
    if hid not in _RING:
        import numpy as np
        with np.load(os.path.join(HEADS_DIR, "前方.npz")) as d:
            H = d[hid].astype(float)
        _RING[hid] = H[[{30: 0, 0: 1, -30: 2}[a] for a in RING_AZ]]
    return _RING[hid]


def ring_clip(np, hid, sr):
    """粉紅噪音在前方左右來回（每個頭都用同一段噪音，只差在頭部量測），音量對齊 → (取樣, 2) float32"""
    fs = 96000
    n_on, step = int(RING_ON * fs), int(RING_STEP * fs)
    total = step * len(RING_AZ) + int(RING_PAUSE * fs)
    spec = np.fft.rfft(np.random.default_rng(7).standard_normal(n_on))
    k = np.arange(len(spec), dtype=float)
    k[0] = 1
    noise = np.fft.irfft(spec / np.sqrt(k), n_on)  # 粉紅噪音：每個八度能量一樣
    noise *= np.minimum(1, np.minimum(np.arange(n_on), n_on - 1 - np.arange(n_on)) / (fs * 0.01))
    H = head_ring(hid)
    m = 1 << (n_on + H.shape[2]).bit_length()
    out = np.zeros((total + m, 2))
    N = np.fft.rfft(noise, m)
    for i in range(len(RING_AZ)):
        y = np.fft.irfft(N[None] * np.fft.rfft(H[i], m, axis=1), m, axis=1)
        out[i * step:i * step + m] += y.T
    out = out[:total]
    out *= 0.05 / np.sqrt((out ** 2).mean())  # 約 -26 dBFS
    return (_resample(out, sr) if sr != fs else out).astype("float32")


def apo_selftest(cfg_dir, dev):
    """用 Equalizer APO 自己的檢查工具（Benchmark），照這個裝置現在的格式真的讀一次設定、處理 1 秒聲音
    （只讀，不改任何東西）→ (問題清單, 即時運算佔一個 CPU 核心的 %)"""
    exe = os.path.join(os.path.dirname(cfg_dir), "Benchmark.exe")
    if not dev:
        return ["還沒選輸出裝置"], None
    if not os.path.exists(exe):
        return ["找不到 Equalizer APO 的檢查工具（Benchmark.exe）"], None
    fmt = parse_fmt(dev["fmt"])
    cmd = [exe, "-r", str(fmt[1] if fmt else 48000), "-l", "1", "-v", "--nopause",
           "--devicename", dev.get("iface") or "", "--guid", dev["guid"]]
    try:
        out = subprocess.run(cmd, cwd=os.path.dirname(exe), capture_output=True, timeout=120,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        return [f"檢查工具執行失敗：{e}"], None
    text = (out.stdout + out.stderr).decode("mbcs", "replace")
    probs = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ("(ERROR)" in ln or "(WARNING)" in ln or
                (not ln.startswith("(TRACE)") and re.search(r"error|fail|unable|cannot|could not|not found", ln, re.I))):
            probs.append(re.sub(r"^\((ERROR|WARNING)\)\s*", "", ln))
    if out_name(dev["guid"]).lower() not in text.lower():
        probs.append("Equalizer APO 沒有讀到調音台的設定")
    m = re.search(r"([\d.]+)% CPU load", text)
    return probs, float(m.group(1)) if m else None


def build_config(filters, width=0, crossfeed=0, balance=0.0, reverb_files=None, extra=0.0, headroom=None,
                 xfeed=None, recon=None, sep=None):
    """產生設定檔內容。音量固定降 HEADROOM（＋extra），EQ 關閉時也一樣。
    width＝聲場加寬百分比、crossfeed＝交叉饋送等級、balance＝左右平衡（正＝偏右）、reverb_files＝{取樣率: 殘響檔}、
    xfeed＝{取樣率: 交叉饋送檔}、recon＝{取樣率: 重建濾波檔}"""
    k = width / 100
    lines = ["# written by headphone tuner", f"Preamp: {-((HEADROOM if headroom is None else headroom) + extra):.1f} dB"]
    lines += sep or []  # 分離度外掛：在等化器前面（看到的是原本的左右關係）
    lines += [f"Filter: ON {t} Fc {fc:g} Hz Gain {g:.1f} dB Q {q:.2f}" for t, fc, g, q in filters]
    if crossfeed and xfeed:  # 頭部模型算的交叉饋送（每個取樣率一份）
        lines += xfeed_lines(xfeed)
    elif crossfeed:  # 沒有 numpy 時的舊版：轉成中(M)/側(S) → 只把低頻的側訊號變小 → 低頻互相滲一點過去，像聽喇叭
        _name, gain, fc = CROSSFEED[crossfeed]
        lines += ["Copy: L=0.5*L+0.5*R R=0.5*L+-0.5*R", "Channel: R",
                  f"Filter: ON LSC Fc {fc} Hz Gain {gain:.1f} dB Q 0.50",
                  "Channel: all", "Copy: L=L+R R=L+-1*R"]  # 注意：一定要寫 -1*R，寫 -R 會變成直流訊號
    if k:  # 左右聲道差異放大 → 聲場變寬
        lines.append(f"Copy: L={1 + k:.2f}*L+{-k:.2f}*R R={1 + k:.2f}*R+{-k:.2f}*L")
    if balance:  # 只壓低另一邊，不會多加音量
        side = "L" if balance > 0 else "R"
        lines.append(f"Copy: {side}={10 ** (-abs(balance) / 20):.4f}*{side}")
    if reverb_files:  # 殘響：直達聲＋空間反射（每個取樣率一份）
        lines += reverb_lines(reverb_files)
    if recon:  # 最後：電腦重建濾波（只在 88.2 kHz 以上）
        lines += recon_lines(recon)
    return "\n".join(lines) + "\n"


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
    # 同一款耳機在資料庫裡寫法不同（大小寫、空格，例如 AirPods Pro2／Airpods Pro 2）→ 合併，量測份數才多
    groups = {}
    for name, ent in models.items():
        g = groups.setdefault(re.sub(r"[^0-9a-z]", "", name.lower()), [[], []])
        g[0].append(name)
        g[1].extend(ent)
    # 顯示名稱取大寫、空格最多的寫法（AirPods Pro 2 比 Airpods Pro2 正確）
    nice = lambda n: (sum(c.isupper() for c in n), n.count(" "))
    models = {max(names, key=nice): ent for names, ent in groups.values()}
    # 資料庫沒量過的型號：用同系列、同年代的兄弟機量測推估（兩支交錯取，「多份平均」＝兩支的平均）
    tag = lambda sib: sib.split("-")[-1] if "-" in sib else sib.split()[-1]  # 按鈕上標出是哪一支的量測
    for alias, sibs in ESTIMATED.items():
        lists = [[(f"{src}（{tag(sib)}）", link) for src, link in models.get(sib, [])] for sib in sibs]
        ent = [e for group in itertools.zip_longest(*lists) for e in group if e]
        if ent:
            models[alias] = ent
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
    """扁平按鈕：滑過變亮；選中或主要按鈕是橘底白字"""

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
    """滑桿：圓角軌道、從 0 往外填橘色、白色圓把手；可拖曳、點擊、滾輪，雙擊歸零"""

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
        tid = var.trace_add("write", lambda *_: self.draw())
        self.bind("<Destroy>", lambda _e: var.trace_remove("write", tid))

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
    """開關：橘色＝開"""

    def __init__(self, master, app, var, command):
        self.w, self.h = app.px(42), app.px(24)
        super().__init__(master, width=self.w, height=self.h, bg=master["bg"], highlightthickness=0,
                         cursor="hand2")
        self.app, self.var, self.command = app, var, command
        self.bind("<Button-1>", self.click)
        tid = var.trace_add("write", lambda *_: self.draw())
        self.bind("<Destroy>", lambda _e: var.trace_remove("write", tid))
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
        self.presets = s.get("presets", {})
        # 每個輸出裝置各自記住：耳機、調音、音量優先 → {裝置代號: {"headphone", "last", "loud"}}
        self.profiles = s.get("profiles") or {}
        self.dev_guid = s.get("device") or default_device_guid()
        prof = self.profiles.get(self.dev_guid or "", {})
        last = prof.get("last", s.get("last", {}))  # 舊版設定檔沒有 profiles：沿用
        self.hp = prof.get("headphone", s.get("headphone"))  # {"name", "sources": [[來源, 濾波器], ...]}
        set_headphone(self.hp)
        update_headroom()
        dev = find_device(self.dev_guid)
        self.loud = tk.BooleanVar(value=prof.get("loud", bool(dev and dev["bt"] == "stereo")))
        self.follow = tk.BooleanVar(value=s.get("follow", True))
        self._perm_asked = False
        self.eq_problem = None  # 每 2 秒在 refresh_device 更新
        self._ir_jobs, self._ir_ready, self._clean_job = set(), False, None  # 背景做殘響檔
        self.sep_level = tk.IntVar(value=int(s.get("sep", 0)))  # 分離度：關／輕／中／強（所有風格都套用）
        self._sep_name = None
        self.hf_all = s.get("hf") or {}  # 高頻校正：{耳機名稱: 測驗結果}
        self.hf_data, self.hf_on = {}, tk.BooleanVar(value=False)
        self.load_hf()
        pf = s.get("pref") or {}
        self.pref_data = pf if "bass" in pf else {}  # 聲音偏好測驗的結果
        self.pref_on = tk.BooleanVar(value=bool(self.pref_data and pf.get("on", True)))
        self._test = None  # 個人化測驗中暫時用的設定
        self._hf = self._pref = self._hf_win = self._head = None
        self._head_pop, self._head_pop_t = None, 0.0
        HEAD_USE[0] = s.get("head") if s.get("head") in head_sets() else "KU100"
        self._selftest, self._st_busy, self.st_probs = None, False, []
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
        self.hist, self.fut, self._last_snap = [], [], None  # 上一步／下一步
        self._base_curves = {}  # 耳機校正的曲線快取（拖滑桿時不用每次重算）
        self._tip = self._tip_job = None
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        pick_fonts(root)
        self.style_theme()
        self.build()
        root.update_idletasks()
        self.fit_style_grid()
        self.fit_source_box()
        self.fit_screen()
        self.changed()
        self.tick()
        self.dev_chip.bind("<Button-1>", lambda _e: self.run_selftest(show=True))
        self.dev_chip.config(cursor="hand2")
        self.root.after(8000, self.run_selftest)  # 開啟後自動檢查一次（Equalizer APO 真的讀一次設定）
        if self.hp and len({src for src, _f in self.hp.get("sources", [])}) >= 2 and "consensus" not in self.hp:
            self.start_consensus(self.hp["name"])  # 舊版選的耳機：補算多源共識
        start_hotkeys(root, {1: self.hotkey_toggle_eq, 2: lambda: self.hotkey_style(1),
                             3: lambda: self.hotkey_style(-1)}, self.hotkey_failed)
        # 版面排好後把視窗大小固定住：之後文字變長變短都不會讓視窗跳動
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        aw, ah = work_area() or (root.winfo_screenwidth(), root.winfo_screenheight())
        x = max(0, (aw - w) // 2)  # 開在工作區正中間（不含工作列），下面才不會跑出螢幕
        y = max(0, (ah - h - self.px(40)) // 2)  # 標題列約 40 px 也算進去
        root.geometry(f"{w}x{h}+{x}+{y}")
        # 視窗內快捷鍵：空白鍵開關 EQ、←→ 換風格、數字鍵換分頁
        key = lambda fn: (lambda _e: None if self.typing() else fn())  # 在搜尋框打字時不觸發
        root.bind("<space>", key(self.hotkey_toggle_eq))
        root.bind("<Right>", key(lambda: self.hotkey_style(1)))
        root.bind("<Left>", key(lambda: self.hotkey_style(-1)))
        root.bind("<Control-z>", key(self.undo))
        root.bind("<Control-y>", key(self.redo))
        for k in range(len(STYLE_GROUPS)):
            root.bind(str(k + 1), key(lambda g=k: self.show_group(g)))
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
            dev = find_device(self.dev_guid)
            self.choose_headphone(dev["iface"] if dev and dev["bt"] else "")

    def setup_config(self):
        dev = find_device(self.dev_guid)
        if not dev:
            return
        allds = list_devices()
        keep = {g.lower() for g in self.profiles} | {dev["guid"].lower()}
        try:
            if ensure_config(self.cfg_dir, [d for d in allds if d["guid"].lower() in keep], [d["guid"] for d in allds]):
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
        Pill(head, self, "？ 怎麼用", self.show_guide, size=9).pack(side="right", padx=(0, px(8)))
        self.ab_btn = Pill(head, self, "按住聽原音", lambda: None, size=9)
        self.ab_btn.pack(side="right", padx=(0, px(8)))
        self.ab_btn.bind("<ButtonPress-1>", lambda _e: self.hold_original(True), add="+")
        self.ab_btn.bind("<ButtonRelease-1>", lambda _e: self.hold_original(False), add="+")

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
        self.toggle_row(c, "音量優先", "比較大聲，換風格音量會變（藍牙建議）", self.loud, self.changed)
        hrow = tk.Frame(c, bg=PANEL)
        hrow.pack(fill="x", pady=(px(8), px(2)))
        self.label(hrow, "耳機校正（AutoEQ 量測，目標 Harman 2018）", 8, SUB).pack(side="left")
        self.hf_pill = Pill(hrow, self, "", self.hf_dialog, size=8)
        self.hf_pill.config(pady=0)  # 跟標題同高，視窗不會變高
        self.hf_pill.pack(side="right")
        self.paint_hf()
        grid = tk.Frame(c, bg=PANEL)
        grid.pack(fill="x")
        self.base_grid = grid
        self.build_base_pills()
        grid.columnconfigure((0, 1), weight=1, uniform="b")

        # 左：快速風格
        c = self.card(left, "快速風格")
        top = c.winfo_children()[0]
        self.search_var = tk.StringVar()
        ent = tk.Entry(top, textvariable=self.search_var, font=(FONT, 10), relief="flat", bg=PILL, fg=TEXT,
                       insertbackground=TEXT, width=14, highlightthickness=1, highlightbackground=LINE,
                       highlightcolor=ACCENT)
        ent.pack(side="right", ipady=px(2))
        ent.bind("<Escape>", lambda _e: (self.search_var.set(""), self.root.focus_set()))
        self.label(top, "搜尋", 9, SUB).pack(side="right", padx=(0, px(6)))
        self.search_var.trace_add("write", lambda *_: self.search_styles())
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
        c = self.card(mid, "EQ 曲線", "橘線＝整體效果　咖啡色虛線＝你的細調")
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
        Pill(row, self, "↶ 上一步", self.undo, size=9).pack(side="left")
        Pill(row, self, "↷ 下一步", self.redo, size=9).pack(side="left", padx=px(6))
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x", pady=(px(8), 0))
        Pill(row, self, "匯出給手機", self.export_phone, size=9).pack(side="left")
        self.label(row, "存成手機等化器 App 能讀的檔案（同一副耳機才準）", 8, SUB).pack(side="left", padx=px(8))

        # 右：空間感與平衡
        c = self.card(right, "空間感與平衡")
        self.sep_pill = Pill(c.winfo_children()[0], self, "", self.cycle_sep, size=9)
        self.sep_pill.pack(side="left", padx=(px(10), 0))
        self.paint_sep()
        g = tk.Frame(c, bg=PANEL)
        g.pack(fill="x")
        self.width_lbl = self.slider_row(g, 0, "聲場寬度", "左右拉開", self.width, 0, 40, 5, 180)
        self.cf_lbl = self.slider_row(g, 1, "交叉饋送", "最右＝虛擬喇叭", self.crossfeed, 0, 4, 1, 180, num=False)
        self.head_lbl = g.grid_slaves(row=1, column=0)[0].winfo_children()[1]  # 小字加上「頭型」，點一下挑
        self.head_lbl.config(cursor="hand2")
        self.head_lbl.bind("<Button-1>", lambda _e: self.head_menu())
        self.paint_head()
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
        self.label(c, "DAC 支援就選 32-bit／352.8：電腦做重建濾波、\nEQ 高頻更準。切換時音樂會停一下，再按播放。",
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
        self.hk_lbl = self.label(foot, "空白鍵 開關EQ　←→ 換風格　Ctrl+Z 上一步　全域：" +
                                 "　".join(f"{n} {d}" for _i, _m, _v, n, d in HOTKEYS), 9, SUB)
        self.hk_lbl.pack(side="right")
        self.attach_help(r)

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
        name = ("藍牙 · " + dev["iface"]) if dev and dev["bt"] else (dev["name"] if dev else "還沒選（點我選）")
        self.devsel_btn.config(text="輸出：" + cut(name, 30))

    # ---------- 選耳機、選裝置 ----------
    def dialog(self, title, hint):
        px = self.px
        win = tk.Toplevel(self.root, bg=PANEL)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        self.label(win, hint, 10, SUB, justify="left").pack(anchor="w", padx=px(16), pady=(px(12), px(6)))
        return win

    def choose_headphone(self, query=""):
        px = self.px
        win = self.dialog("選擇耳機", "輸入耳機型號（例：HD 600、XM5、AirPods Max），資料來自 AutoEQ 資料庫。\n"
                                    "無線耳機有「ANC on／off」兩種量測的，選你平常用的模式。")
        entry = tk.Entry(win, font=(FONT, 12), relief="flat", bg=PILL, fg=TEXT, insertbackground=TEXT)
        entry.pack(fill="x", padx=px(16), ipady=px(4))
        entry.insert(0, query)
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
            if len({src for src, _p in state["models"][name]}) >= 2:
                self.start_consensus(name, state["models"][name])  # 背景下載所有量測、算多源共識
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
        self._base_curves.clear()
        set_headphone(hp)
        self.load_hf()
        update_headroom()
        self.build_base_pills()
        self.base.set(default_base())
        self.paint_header()
        self.changed()
        self.toast(f"耳機：{hp['name']}（音量預留 {HEADROOM:g} dB）")

    def choose_device(self):
        px = self.px
        win = self.dialog("選擇輸出裝置", "選你的耳機接在哪個裝置（解碼器、耳擴、音效卡、藍牙耳機）。\n"
                                        "每個裝置會各自記住它的耳機和調音。")
        devs = sorted((d for d in list_devices() if d["active"]),
                      key=lambda d: (d["bt"] == "handsfree", not d["hooked"], d["name"]))

        def pick(d):
            if d["bt"] == "handsfree" and not messagebox.askyesno(
                    "藍牙通話模式", "這是藍牙耳機的「通話模式」：單聲道、音質很差，只有在講電話時才會用到。\n\n"
                                "聽音樂請選同一副耳機的另一個（立體聲）項目。確定還是要選這個嗎？", parent=win):
                return
            win.destroy()
            self.set_device(d)

        for d in devs:
            tags = (["藍牙"] if d["bt"] == "stereo" else ["藍牙通話模式：單聲道、音質差"] if d["bt"] else [])
            tags.append("EQ 已接上" if d["hooked"] else "EQ 還沒接上")
            p = Pill(win, self, f"{d['name']}　（{'・'.join(tags)}）", lambda d=d: pick(d), size=10)
            p.set_selected(d["guid"].lower() == (self.dev_guid or "").lower())
            p.pack(fill="x", padx=px(16), pady=px(3))
        if not devs:
            self.label(win, "沒有偵測到任何輸出裝置", 10, ORANGE).pack(padx=px(16))
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=px(16), pady=(px(12), px(14)))
        Toggle(row, self, self.follow, self.save_settings).pack(side="right", padx=(px(12), 0))
        self.label(row, "自動跟著 Windows 目前的輸出切換", 10, bold=True).pack(anchor="w")
        self.label(row, "例如藍牙耳機一連上，調音台就切到它、用它自己的設定", 8, SUB).pack(anchor="w")

    def load_profile(self, p):
        """換到某個裝置：載入它記住的耳機、調音、音量優先"""
        self.hp = p.get("headphone")
        self._base_curves.clear()
        set_headphone(self.hp)
        self.load_hf()
        update_headroom()
        self.build_base_pills()
        last = p.get("last", {})
        self.enabled.set(last.get("enabled", True))
        self.passthrough.set(last.get("passthrough", False))
        self.loud.set(p.get("loud", False))
        self.apply_snap(last)

    def set_device(self, dev, auto=False):
        if dev["guid"].lower() == (self.dev_guid or "").lower():
            return
        self.save_settings()  # 先把目前裝置的設定記起來
        self.dev_guid = dev["guid"]
        p = self.profiles.get(self.dev_guid)
        if p:
            self.load_profile(p)
        else:  # 第一次用的裝置：沿用目前的耳機和調音；藍牙預設音量優先
            self.loud.set(dev["bt"] == "stereo")
        self.hist.clear()
        self.fut.clear()
        self._last_snap = None
        self.pend_fmt = None
        self.paint_header()
        if os.path.isdir(self.cfg_dir):
            self.setup_config()
        self.changed()
        self.save_settings()
        self.toast(("自動切換到：" if auto else "輸出：") + dev["name"])
        if p is None and dev["bt"]:
            self.choose_headphone(dev["iface"])  # 新的藍牙耳機：用它的名字幫你先搜尋型號
        elif not dev["hooked"] and not auto:
            self.open_selector()

    def toggle_row(self, parent, title, sub, var, command):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=self.px(3))
        Toggle(row, self, var, command).pack(side="right")
        self.label(row, title, 10, bold=True).pack(anchor="w")
        self.label(row, sub, 8, SUB).pack(anchor="w")

    def show_group(self, gi):
        """切換快速風格分頁（會清掉搜尋）"""
        self.group = gi
        if getattr(self, "search_var", None) is not None and self.search_var.get():
            self._quiet_search = True
            self.search_var.set("")
            self._quiet_search = False
        start = sum(len(g) for _n, g in STYLE_GROUPS[:gi])
        self.show_list(list(range(start, start + len(STYLE_GROUPS[gi][1]))), gi)

    def show_list(self, idxs, gi=None):
        """在按鈕區顯示這些風格；每次固定一樣多格（依最多的那頁），不足補空白，版面高度才不會變"""
        px = self.px
        for i, (lbl, bar) in enumerate(self.tabs):
            lbl.config(fg=TEXT if i == gi else SUB)
            bar.config(bg=ACCENT if i == gi else PANEL)
        for w in self.style_grid.winfo_children():
            w.destroy()
        self.style_btns = {}
        slots = 3 * math.ceil(max(len(g) for _n, g in STYLE_GROUPS) / 3)
        for j in range(slots):
            if j < len(idxs):
                i = idxs[j]
                w = Pill(self.style_grid, self, STYLES[i][0], lambda i=i: self.apply_style(i), size=9)
                self.style_btns[i] = w
                w.bind("<Enter>", lambda _e, i=i: self.show_info(i), add="+")
                w.bind("<Leave>", lambda _e: self.show_info(self.current_style()), add="+")
            elif j == 0:
                w = tk.Label(self.style_grid, text="找不到，換個字試試（例：搖滾、人聲、低音）", font=(FONT, 9),
                             bg=PANEL, fg=SUB, pady=px(5))
                w.grid(row=0, column=0, columnspan=3, sticky="w", padx=px(4), pady=px(2))
                continue
            elif not idxs and j < 3:  # 第一排被「找不到」的說明占用
                continue
            else:
                w = tk.Label(self.style_grid, text=" ", font=(FONT, 9), bg=PANEL, pady=px(5))
            w.grid(row=j // 3, column=j % 3, sticky="ew", padx=px(2), pady=px(2))
        self.style_grid.columnconfigure((0, 1, 2), weight=1, uniform="s")
        self.highlight_style(self.current_style())

    def search_styles(self):
        """搜尋框：比對風格名稱和白話介紹（所有分頁一起找）"""
        if getattr(self, "_quiet_search", False):
            return
        q = self.search_var.get().strip().lower()
        if not q:
            self.show_group(self.group)
            return
        self.show_list([i for i, st in enumerate(STYLES) if q in st[0].lower() or q in PLAIN.get(st[0], "").lower()])

    def typing(self):
        return isinstance(self.root.focus_get(), tk.Entry)

    # ---------- 更直覺：按住聽原音、名詞說明、怎麼用、上一步 ----------
    def hold_original(self, down):
        """按住＝暫時關掉 EQ（音量不變），放開就回來"""
        if self.passthrough.get():
            return
        if down and self.enabled.get():
            self._holding = True
            self.enabled.set(False)
        elif not down and getattr(self, "_holding", False):
            self._holding = False
            self.enabled.set(True)
        else:
            return
        self.ab_btn.set_selected(down)
        self.redraw()
        self.write_config()

    def attach_help(self, widget):
        """畫面上跟 HELP 同名的標籤：滑鼠移上去跳出白話說明"""
        for w in widget.winfo_children():
            if type(w) is tk.Label and w.cget("text") in HELP:
                self.tip(w, HELP[w.cget("text")])
            self.attach_help(w)

    def tip(self, widget, text):
        widget.config(cursor="question_arrow")

        def show():
            self.hide_tip()
            t = self._tip = tk.Toplevel(self.root, bg=TIP_BG)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            tk.Label(t, text=text, font=(FONT, 10), fg="white", bg=TIP_BG, justify="left",
                     wraplength=self.px(340), padx=self.px(12), pady=self.px(8)).pack()
            t.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + self.px(4)}")

        def enter(_e):
            self._tip_job = self.root.after(300, show)

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", lambda _e: self.hide_tip(), add="+")

    def hide_tip(self):
        if self._tip_job:
            self.root.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def show_guide(self):
        px = self.px
        win = self.dialog("怎麼用", "六個步驟就上手：")
        for n, (title, text) in enumerate(GUIDE, 1):
            row = tk.Frame(win, bg=PANEL)
            row.pack(fill="x", padx=px(16), pady=px(4))
            tk.Label(row, text=str(n), font=(NUM, 11, "bold"), fg="white", bg=ACCENT, width=2).pack(side="left", anchor="n")
            box = tk.Frame(row, bg=PANEL)
            box.pack(side="left", fill="x", padx=px(10))
            self.label(box, title, 11, bold=True).pack(anchor="w")
            self.label(box, text, 10, SUB, justify="left", wraplength=px(520)).pack(anchor="w")
        Pill(win, self, "知道了", win.destroy, primary=True).pack(anchor="e", padx=px(16), pady=(px(8), px(14)))

    TUNE_KEYS = ("base", "bands", "width", "crossfeed", "balance", "room")

    def record(self):
        """設定穩定下來（寫進 EQ）時記一筆，給「上一步」用"""
        snap = {k: self.snapshot()[k] for k in self.TUNE_KEYS}
        if self._last_snap is not None and snap != self._last_snap:
            self.hist.append(self._last_snap)
            del self.hist[:-50]
            self.fut.clear()
        self._last_snap = snap

    def apply_snap(self, p):
        self.base.set(p.get("base") if p.get("base") in BASES else default_base())
        self.balance.set(p.get("balance", 0))
        self.room.set(p.get("room", 0))
        self.set_bands(p.get("bands", [0] * len(BANDS)), p.get("width", 0), p.get("crossfeed", 0))

    def undo(self):
        if not self.hist:
            self.toast("沒有上一步了")
            return
        self.fut.append(self._last_snap)
        self._last_snap = self.hist.pop()
        self.apply_snap(self._last_snap)
        self.toast("↶ 上一步")

    def redo(self):
        if not self.fut:
            self.toast("沒有下一步了")
            return
        self.hist.append(self._last_snap)
        self._last_snap = self.fut.pop()
        self.apply_snap(self._last_snap)
        self.toast("↷ 下一步")

    def export_phone(self):
        """把耳機校正＋細調合成一條曲線，存成 AutoEQ 的 GraphicEQ 格式（手機等化器 App 多半能匯入），也複製到剪貼簿"""
        base, style = self.filters()
        freqs = [20 * 1000 ** (i / 126) for i in range(127)]
        gains = [sum(filter_db(*fl, f) for fl in base + style) for f in freqs]
        top = max(gains)
        text = "GraphicEQ: " + "; ".join(f"{f:.0f} {g - max(0.0, top):.1f}" for f, g in zip(freqs, gains))
        idx = self.current_style()
        name = re.sub(r'[\\/:*?"<>|]', "_", STYLES[idx][0] if idx >= 0 else "我的調音")
        path = filedialog.asksaveasfilename(parent=self.root, title="匯出給手機", initialfile=f"{name} GraphicEQ.txt",
                                            defaultextension=".txt", filetypes=[("文字檔", "*.txt")])
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        messagebox.showinfo("匯出給手機", ("已存成檔案，也" if path else "") + "複製到剪貼簿了。\n\n"
                            "在手機的等化器 App 選「匯入 AutoEQ／GraphicEQ」（例如 JamesDSP 的任意響應等化器、Wavelet），"
                            "貼上或選這個檔案就好。\n\n只包含耳機校正和細調；聲場寬度、交叉饋送、殘響不會帶過去。",
                            parent=self.root)

    def fit_screen(self):
        """螢幕比較小（例如筆電 150% 縮放）時整個畫面等比例縮小重畫，視窗才不會超出螢幕"""
        self.root.update_idletasks()
        area = work_area()
        if not area:
            return
        # 標題列（約 40 px）也要算進去，不然視窗下緣會跑出螢幕
        f = min(1.0, area[0] / self.root.winfo_reqwidth(), (area[1] - self.px(40)) / self.root.winfo_reqheight())
        if f >= 0.99:
            return
        f *= 0.98
        self.scale *= f
        self.root.tk.call("tk", "scaling", float(self.root.tk.call("tk", "scaling")) * f)
        for w in self.root.winfo_children():
            w.destroy()
        self.style_theme()
        self.build()
        self.root.update_idletasks()
        self.fit_style_grid()
        self.fit_source_box()

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
        if self._ir_ready:  # 背景做好其他取樣率的殘響檔 → 寫進設定
            self._ir_ready = False
            self.write_config()
        hf = False
        if self.follow.get() and not getattr(self, "_holding", False):
            g = default_device_guid(strict=True)
            if g and g.lower() != (self.dev_guid or "").lower():
                d = find_device(g)
                if d and d["active"]:
                    if d["bt"] == "handsfree":
                        hf = True  # 講電話中：不切過去，只提示
                    else:
                        self.set_device(d, auto=True)
        dev = find_device(self.dev_guid)
        if self._selftest:
            self.selftest_done()
        self.refresh_device(dev, hf)
        self.refresh_format(dev)
        self.refresh_playback(dev)
        self.root.after(2000, self.tick)

    def refresh_device(self, dev, hf=False):
        if hf:
            self.dev_chip.config(text="● 藍牙通話模式中：單聲道、音質差（掛斷就恢復）", fg=ORANGE, bg=ORANGE_BG)
            self.fix_btn.pack_forget()
            return
        self.eq_problem = None
        if dev and dev["hooked"] and dev["active"]:
            self.eq_problem = config_problem(self.cfg_dir, dev)
            if not self.eq_problem:
                if self.st_probs:  # 自我檢查（Equalizer APO 真的讀一次設定）發現問題
                    self.dev_chip.config(text="● 自我檢查發現問題（點這裡看）", fg=ORANGE, bg=ORANGE_BG)
                else:
                    self.dev_chip.config(text="● EQ 已接上", fg=GREEN, bg=GREEN_BG)
                self.fix_btn.pack_forget()
                return
            text, btn, cmd = f"● {self.eq_problem}", "一鍵修復", self.repair_config
        else:
            self.eq_problem = "EQ 沒接上"
            text = (("● EQ 還沒接上這個裝置" if dev["active"] else "● 藍牙耳機沒連線" if dev["bt"] else "● 裝置沒插上")
                    if dev else "● 還沒選輸出裝置")
            btn, cmd = "點我接上", self.open_selector
            dev = dev if dev and dev["active"] and not dev["hooked"] else None
        self.dev_chip.config(text=text, fg=ORANGE, bg=ORANGE_BG)
        self.fix_btn.config(text=btn)
        self.fix_btn.command = cmd
        if dev and not self.fix_btn.winfo_ismapped():
            self.fix_btn.pack(side="right")

    def repair_config(self):
        if not messagebox.askokcancel("修復設定檔", f"{self.eq_problem}。\n\n通常是其他等化器程式（或另一個調音台）改了 Equalizer APO 的設定。\n"
                                      "要讓這個裝置重新只套用調音台嗎？\n（其他程式的設定會保留，只是不再套用到這個裝置）",
                                      parent=self.root):
            return
        self.setup_config()
        self.refresh_device(find_device(self.dev_guid))
        self.toast("已修復" if not self.eq_problem else "還是有問題，請到 GitHub 回報")

    def eq_mode(self):
        """播放資訊列最右邊的狀態：EQ 真的有在作用才顯示綠色"""
        if self.passthrough.get():
            return "共用模式 · 直通（不處理）", SUB, PILL
        if not self.enabled.get():
            return "共用模式 · EQ 關閉（原音）", SUB, PILL
        if self.eq_problem:
            return "共用模式 · EQ 沒套用", ORANGE, ORANGE_BG
        return "共用模式 · EQ 有效", GREEN, GREEN_BG

    def open_selector(self):
        apo = os.path.dirname(self.cfg_dir)
        # 一定要從安裝資料夾啟動，不然會出現 Qt platform plugin 錯誤
        ctypes.windll.shell32.ShellExecuteW(None, "runas", os.path.join(apo, "DeviceSelector.exe"), None, apo, 1)
        dev = find_device(self.dev_guid)
        name = dev["iface"] if dev else "你的輸出裝置"
        tip = ("\n\n藍牙耳機裝了還是沒效果的話：在同一個視窗勾選「Troubleshooting options」，\n"
               "選「Install as SFX/EFX (experimental)」，按確定再重新開機。" if dev and dev["bt"] else "")
        messagebox.showinfo("接上 EQ", f"在跳出的視窗勾選「{name}」→ 按確定，\n然後重新開機就完成了。" + tip, parent=self.root)

    def refresh_format(self, dev):
        self.cur_bt = bool(dev and dev["bt"])
        cur = parse_fmt(dev["fmt"]) if dev and dev["active"] else None
        self.cur_fmt = cur[:2] if cur else None
        if self.cur_fmt and (int(self.room.get()) and self.cur_fmt[1] != getattr(self, "_ir_rate", None)
                             or self.recon_on() != getattr(self, "_hires", False)):
            self.changed()  # DAC 取樣率變了 → 殘響檔換成新的取樣率；跨過 88.2 kHz → 重建濾波的防破音重算
        if self.pend_fmt is None and self.cur_fmt:
            self.pend_fmt = self.cur_fmt
        self.paint_format()

    def pick_format(self, bits=None, rate=None):
        if not self.pend_fmt:
            return
        self.pend_fmt = (bits or self.pend_fmt[0], rate or self.pend_fmt[1])
        self.paint_format()

    def paint_format(self):
        if getattr(self, "cur_bt", False):
            for p in list(self.depth_pills.values()) + list(self.rate_pills.values()):
                p.set_selected(False)
            self.fmt_lbl.config(text="藍牙：格式由藍牙編碼決定，這裡不能改")
            return
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
                                 + ("　→ 按套用" if changed else "　電腦重建濾波" if self.recon_on() else ""))
        if self.apply_btn.primary != changed:
            self.apply_btn.primary = changed
            self.apply_btn.paint()

    def recon_on(self):
        """裝置在 88.2 kHz 以上 → 電腦做重建濾波"""
        return bool(self.cur_fmt) and self.cur_fmt[1] >= RECON_MIN

    def apply_format(self):
        dev = find_device(self.dev_guid)
        if dev and dev["bt"]:
            messagebox.showinfo("輸出解析度", "藍牙耳機的音質由藍牙編碼（SBC、AAC、aptX…）決定，\n"
                                "Windows 會自動挑，這裡不能改。", parent=self.root)
            return
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
            put("mode", *self.eq_mode())
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
        if dev and info.get("dev") and info["dev"] != dev["guid"].lower():
            # Tidal 輸出到別的裝置（例如 Tidal 設定裡指定了別的裝置）：聲音沒經過調音台正在調的這個裝置
            other_dev = find_device(info["dev"])
            put("dac", "")
            put("mode", f"Tidal 輸出到「{other_dev['iface'] if other_dev else '別的裝置'}」· 這個裝置的 EQ 沒套用到", ORANGE, ORANGE_BG)
        elif out and (info.get("mode") == "exclusive"
                      or (info.get("mode") is None and dac and out[1] == rate and out[1] != dac[1])):
            put("dac", f"DAC {out[0]}-bit / {fmt_rate(out[1])}")
            put("mode", "獨佔模式 · EQ 不會生效", ORANGE, ORANGE_BG)
        elif dac:
            put("dac", f"DAC {dac[0]}-bit / {fmt_rate(dac[1])}")
            put("mode", *self.eq_mode())
        else:
            put("dac", "")
            put("mode", "")

    # ---------- 調整 ----------
    def toggle_passthrough(self):
        if self.passthrough.get() and not messagebox.askokcancel(
                "直通模式",
                f"直通模式完全不處理聲音，也不會預留音量，\n聲音會突然變大約 {HEADROOM:g} dB（非常大聲）。\n\n"
                "請先把解碼器／耳擴的音量轉小，再按「確定」。", parent=self.root):
            self.passthrough.set(False)
        self.changed()

    def pick_base(self, key):
        self.base.set(key)
        self.changed()

    def filters(self):
        base = list(BASES[self.base.get()][1]) + self.hf_comp() + self.pref_comp()
        style = [(k, f, round(v.get(), 1), q) for (_n, k, f, q, _h), v in zip(BANDS, self.bands) if v.get()]
        return base, style

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
        key = (self.base.get(), (self.hp or {}).get("name"))
        if key not in self._base_curves:
            self._base_curves[key] = curve(base)
        total = ([a + b for a, b in zip(self._base_curves[key], curve(style))] if on and (base or style)
                 else [0.0] * len(FREQS))
        pts = [c for f, db in zip(FREQS, total) for c in (x(f), y(db))]
        cv.create_polygon(x(FREQS[0]), y(0), *pts, x(FREQS[-1]), y(0), fill=FILL, outline="")
        cv.create_line(L, y(0), W - R, y(0), fill=ZERO_LINE)
        if on and style:
            spts = [c for f, db in zip(FREQS, curve(style)) for c in (x(f), y(db))]
            cv.create_line(*spts, fill=TWEAK, width=px(1.5), dash=(4, 3))
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
                           fill=VALUE, font=(FONT, 9, "bold"))

    def write_config(self):
        self._job = None
        if not getattr(self, "_holding", False):
            self.record()
        base, style = self.filters()
        test = self._test  # 個人化測驗中：用測驗的設定，風格、殘響、聲場、分離度先拿掉
        if test:
            style = test["style"]
        through = self.passthrough.get() and not test
        on = (self.enabled.get() or bool(test)) and not through
        room, files, note = 0 if test else int(self.room.get()), {}, ""
        if room:  # 偵測不到取樣率時也用已經做好的常見取樣率殘響檔（以前會整段拿掉，之後同取樣率回來也不會補回）
            try:
                files = self.reverb_files(room)
            except Exception as e:  # 沒有 numpy 或寫不進去
                note = f"（殘響做不出來：{e}）"
            if not files and not note:
                note = "（殘響檔準備中）"
        filters, width, cf = base + style, 0 if test else self.width.get(), 0 if test else int(self.crossfeed.get())
        xfeed, recon = {}, {}
        try:
            xfeed = (spk_files(self.cfg_dir) if cf == SPEAKER else {}) or (xfeed_files(self.cfg_dir, cf) if cf else {})
            recon = recon_files(self.cfg_dir)
        except Exception as e:  # 沒有 numpy 或寫不進去：交叉饋送用舊版、不做重建濾波
            note = note or f"（高解析處理做不出來：{e}）"
        self._hires = hires = bool(recon) and self.recon_on()
        # 用滿格母帶實際算這組設定的輸出峰值。固定預留：超過就整體多降。音量優先：只預留目前設定需要的。
        # 兩種都一樣：EQ 關掉時用同一個音量，A/B 比較才公平
        sep, sname, sv = [], None, SEP_LEVELS[int(self.sep_level.get())][1]
        if sv and on and not test:
            try:
                sname = sep_file(self.cfg_dir)
                sep = sep_lines(self.cfg_dir, sname, sv) if sname else []
            except OSError as e:
                note = note or f"（分離度外掛複製失敗：{e}）"
        self._sep_name = sname if sep else None
        need = true_peak(filters, width, cf, room if files else 0, hires) + SAFETY + (SEP_MARGIN if sep else 0)
        if self.loud.get():
            hr, extra = max(0.0, math.ceil(need * 2) / 2), 0.0
        else:
            hr, extra = HEADROOM, math.ceil(max(0.0, need - HEADROOM) * 10) / 10
        if test:
            extra += test.get("extra", 0.0)  # 偏好測驗：兩個選項的響度對齊
        text = (build_config(filters, width, cf, self.balance.get(), files, extra, hr, xfeed, recon, sep) if on
                else build_config([], extra=extra, headroom=hr, recon=recon))
        if through:  # 不寫 Preamp、不寫任何濾波器 → 訊號原封不動
            text = "# written by headphone tuner\n# passthrough: no processing\n"
        try:
            write_atomic(os.path.join(self.cfg_dir, out_name(self.dev_guid or DUMMY_GUID)), text)
            try:
                os.utime(os.path.join(self.cfg_dir, "config.txt"))  # 提醒 Equalizer APO 重新讀取
            except OSError:
                pass
            if through:
                self.status.config(text="✓ 直通模式：訊號完全不處理（EQ、聲場、固定降音量都暫停）", fg=GREEN)
            else:
                why = "殘響" if files else "加強比較多"
                msg = (f"✓ 已套用　音量優先：只預留 {hr:g} dB（換風格音量會變，開關 EQ 音量一樣）" if self.loud.get() else
                       f"✓ 已套用　{why}：整體多降 {extra:.1f} dB 防破音（開關 EQ 音量仍一樣）" if extra else
                       "✓ 已套用　音量固定，切換設定、開關 EQ 音量都一樣　（關掉視窗 EQ 仍然有效）")
                if test:
                    msg = "個人化測驗中　暫時只留耳機校正"
                self.status.config(text=msg + note, fg=ORANGE if note else GREEN)
        except PermissionError:
            self.status.config(text="✗ 沒有權限寫入 Equalizer APO 的設定資料夾", fg=ORANGE)
            self.fix_permission()
        except OSError as e:
            self.status.config(text=f"✗ 寫入失敗：{e}", fg=ORANGE)
        self.save_settings()
        # 舊的殘響檔等 Equalizer APO 換成新設定後再刪（其他裝置正在用的不刪）
        if self._clean_job:
            self.root.after_cancel(self._clean_job)
        keep = set(files.values()) | set(xfeed.values()) | {self._sep_name} | self.reverb_in_use()
        self._clean_job = self.root.after(5000, lambda: cleanup_reverb(self.cfg_dir, keep))

    def reverb_files(self, room):
        """目前取樣率的殘響檔馬上做；其他常見取樣率在背景做（做完再寫一次設定）→ 回傳 {取樣率: 檔名}"""
        rate = self.cur_fmt[1] if self.cur_fmt else None
        if rate:
            room_file(self.cfg_dir, room, rate)
        self._ir_rate = rate  # None＝沒偵測到取樣率；之後偵測到時 refresh_format 會再寫一次
        rates = sorted(set(REVERB_RATES) | ({rate} if rate else set()))
        todo = [r for r in rates if not os.path.exists(os.path.join(self.cfg_dir, room_name(room, r)))]
        if todo and room not in self._ir_jobs:
            self._ir_jobs.add(room)

            def work():
                try:
                    for r in todo:
                        room_file(self.cfg_dir, room, r)
                except Exception:
                    pass
                self._ir_jobs.discard(room)
                self._ir_ready = True  # tick() 看到就重寫設定（tkinter 只能在主執行緒動）
            threading.Thread(target=work, daemon=True).start()
        return {r: room_name(room, r) for r in rates if os.path.exists(os.path.join(self.cfg_dir, room_name(room, r)))}

    def reverb_in_use(self):
        """其他裝置（例如藍牙耳機）的設定檔還在用的殘響檔"""
        used = set()
        for fn in os.listdir(self.cfg_dir):
            if fn.startswith("tuner_") and fn.endswith(".txt"):
                try:
                    text = open(os.path.join(self.cfg_dir, fn), encoding="ascii", errors="ignore").read()
                    used |= set(re.findall(r"Convolution: (\S+)", text)) | set(re.findall(r"(sep_[0-9a-f]+\.dll)", text))
                except OSError:
                    pass
        return used

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
    # ---------- 分離度 ----------
    def paint_sep(self):
        lv = int(self.sep_level.get())
        self.sep_pill.config(text=f"分離度：{SEP_LEVELS[lv][0]}")
        self.sep_pill.set_selected(lv > 0)

    def cycle_sep(self):
        self.sep_level.set((int(self.sep_level.get()) + 1) % len(SEP_LEVELS))
        self.paint_sep()
        self.changed()

    # ---------- 多源共識（背景下載所有量測、擬合）----------
    def start_consensus(self, name, entries=None):
        def work():
            ent = entries
            if ent is None:
                models, _err = load_headphone_index()
                ent = models.get(name)
            res = consensus_fit(ent) if ent else None
            self.root.after(0, self.got_consensus, name, res)
        threading.Thread(target=work, daemon=True).start()

    def got_consensus(self, name, res):
        if not self.hp or self.hp.get("name") != name:
            return
        self.hp["consensus"] = res or []  # 空的＝試過了（不到兩份或下載失敗），不再重試
        if res:
            self.set_hp(self.hp)
            self.toast(f"多源共識算好了（{res[0]} 份量測），已經改用")
        else:
            self.save_settings()

    # ---------- 個人化：高頻校正、聲音偏好 ----------
    def hf_key(self):
        return (self.hp or {}).get("name", "")

    def load_hf(self):
        """高頻校正跟耳機有關：每支耳機各存一份"""
        d = self.hf_all.get(self.hf_key()) or {}
        self.hf_data = d if d.get("filters") is not None else {}
        self.hf_on.set(bool(self.hf_data and d.get("on", True)))

    def hf_comp(self):
        if (self._test is not None and not self._test.get("hf")) or not self.hf_on.get():
            return []
        return [tuple(fl) for fl in self.hf_data.get("filters", [])]

    def pref_comp(self):
        if (self._test is not None and not self._test.get("pref")) or not self.pref_on.get() or not self.pref_data:
            return []
        return pref_filters(self.pref_data["bass"], self.pref_data["treble"])

    def out_device(self):
        """sounddevice 裡對應現在選的輸出裝置（WASAPI 共用模式，會經過 Equalizer APO）→ (sd, 編號, 取樣率)"""
        import sounddevice as sd
        api = next(i for i, a in enumerate(sd.query_hostapis()) if "WASAPI" in a["name"])
        want = find_device(self.dev_guid)
        dev = next(i for i, d in enumerate(sd.query_devices())
                   if d["hostapi"] == api and d["max_output_channels"] >= 2 and want and want["iface"] in d["name"])
        return sd, dev, int(sd.query_devices(dev)["default_samplerate"])

    def center_on_root(self, win):
        win.update_idletasks()
        r = self.root
        x = r.winfo_rootx() + (r.winfo_width() - win.winfo_reqwidth()) // 2
        y = r.winfo_rooty() + (r.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def paint_hf(self):
        n = ((bool(self.hf_data) and self.hf_on.get()) + (bool(self.pref_data) and self.pref_on.get())
             + (current_head() != "KU100"))
        self.hf_pill.config(text=f"個人化：{n} 項" if n else "個人化")
        self.hf_pill.set_selected(n > 0)

    def hf_dialog(self):
        if self._hf_win:
            self._hf_win.lift()
            return
        win = self._hf_win = tk.Toplevel(self.root, bg=PANEL)
        win.title("個人化")
        win.transient(self.root)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.hf_end)
        self._hf_body = tk.Frame(win, bg=PANEL)
        self._hf_body.pack(fill="both", expand=True, padx=self.px(20), pady=self.px(16))
        self.pers_overview()

    def hf_clear(self):
        for w in self._hf_body.winfo_children():
            w.destroy()
        for key in ("<Left>", "<Right>", "<Return>", "1", "2"):
            self._hf_win.unbind(key)

    def test_stop(self):
        """停掉進行中的測驗：停止測試音、還原設定"""
        for st in (self._hf, self._pref, self._head):
            for key in ("job", "anim"):
                if st and st.get(key):
                    self.root.after_cancel(st[key])
            if st and st.get("sd"):
                try:
                    st["sd"].stop()
                except Exception:
                    pass
        self._hf = self._pref = self._head = None
        if self._test is not None:
            self._test = None
            self.changed()

    def hf_end(self):
        self.test_stop()
        if self._hf_win:
            self._hf_win.destroy()
            self._hf_win = None

    def pers_page(self, title, text, buttons, wrap=640):
        """一頁：標題、說明、右下角按鈕 [(文字, 指令, 主要)]"""
        px, body = self.px, self._hf_body
        self.hf_clear()
        self.label(body, title, 12, bold=True).pack(anchor="w")
        if text:
            self.label(body, text, 9, SUB, justify="left", wraplength=px(wrap)).pack(anchor="w", pady=(px(4), px(10)))
        row = tk.Frame(body, bg=PANEL)
        row.pack(side="bottom", fill="x", pady=(px(12), 0))
        for label, cmd, primary in reversed(buttons):
            Pill(row, self, label, cmd, primary=primary).pack(side="right", padx=(px(6), 0))
        if buttons:
            self._hf_win.bind("<Return>", lambda _e: buttons[-1][1]())
        return body

    def pers_overview(self):
        self.test_stop()
        px = self.px
        body = self.pers_page("個人化", "這三項只跟你有關：你的耳朵、你的喜好、你的頭型。結果套用到所有風格，可以各自開關。",
                              [("關閉", self.hf_end, False)])

        def section(title, desc, result, var, start, start_label):
            box = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
            box.pack(fill="x", pady=(0, px(8)))
            inner = tk.Frame(box, bg=PANEL)
            inner.pack(fill="x", padx=px(12), pady=px(8))
            right = tk.Frame(inner, bg=PANEL)
            right.pack(side="right")
            left = tk.Frame(inner, bg=PANEL)
            left.pack(side="left", fill="x", expand=True)
            self.label(left, title, 10, bold=True).pack(anchor="w")
            self.label(left, desc, 8, SUB, justify="left", wraplength=px(470)).pack(anchor="w")
            self.label(left, result, 9, justify="left", wraplength=px(470)).pack(anchor="w", pady=(px(3), 0))
            if var is not None:
                p = Pill(right, self, "", None, size=9)

                def paint():
                    p.config(text="開" if var.get() else "關")
                    p.set_selected(var.get())

                def flip():
                    var.set(not var.get())
                    paint()
                    self.paint_hf()
                    self.changed()
                p.command = flip
                paint()
                p.pack(side="left", padx=(0, px(6)))
            Pill(right, self, start_label, start, primary=True, size=9).pack(side="left")

        hf = self.hf_data
        peaks = [f"{fc / 1000:.1f} kHz {c:+.1f}" for fc, c in zip(HF_FREQS, hf.get("corr", [])) if abs(c) >= 1]
        res = "還沒測" if not hf else f"{hf.get('date', '')}：" + ("、".join(peaks) + " dB" if peaks else "幾乎不用校正")
        section(f"高頻校正（你的耳朵＋{self.hf_key() or '這支耳機'}）", "3–10 kHz 耳道共振的個人差異。用測試音，約 5 分鐘。",
                res, self.hf_on if hf else None, self.hf_intro, "重新測驗" if hf else "開始測驗")
        pf = self.pref_data
        res = "還沒測" if not pf else f"{pf.get('date', '')}：低音 {pf['bass']:+.1f} dB、高音 {pf['treble']:+.1f} dB（跟標準比）"
        section("聲音偏好（你的喜好）", "用你常聽的歌盲聽比較，找出你最喜歡的低音、高音量。要先播歌，約 8 分鐘。", res,
                self.pref_on if pf else None, self.pref_intro, "重新測驗" if pf else "開始測驗")
        section("頭型（你的頭）", "虛擬喇叭、錄音室殘響、交叉饋送用的頭。從假人頭和 18 位真人裡，只聽前方、一次比兩個，"
                "挑聲音最像在前面的一位。不用播歌，約 5 分鐘。也可以直接點「交叉饋送」底下的「頭型 ▾」換。",
                f"目前：{head_name(current_head())}", None, self.head_intro, "挑選")
        self.center_on_root(self._hf_win)

    # 頭型：「交叉饋送」底下的小字點一下跳出清單直接挑
    def paint_head(self):
        hid = current_head()
        self.head_lbl.config(text=f"最右＝虛擬喇叭　頭型：{'假人頭' if hid == 'KU100' else hid} ▾",
                             fg=SUB if hid == "KU100" else ACCENT)

    def set_head(self, hid):
        HEAD_USE[0] = hid
        self.paint_head()
        self.paint_hf()
        self.changed()

    def head_menu(self):
        if self._head_pop or time.time() - self._head_pop_t < 0.3:  # 再點一次＝收起來
            self.head_menu_close()
            return
        px, cur = self.px, current_head()
        pop = self._head_pop = tk.Toplevel(self.root, bg=LINE)
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        body = tk.Frame(pop, bg=PANEL)
        body.pack(padx=1, pady=1)
        inner = tk.Frame(body, bg=PANEL)
        inner.pack(padx=px(14), pady=px(10))

        def pick(hid):
            self.head_menu_close()
            if hid != cur:
                self.set_head(hid)
                self.toast(f"頭型：{head_name(hid)}")

        self.label(inner, "頭型（點一下馬上換）", 9, SUB).pack(anchor="w")
        grid = tk.Frame(inner, bg=PANEL)
        grid.pack(anchor="w", pady=(px(4), 0))
        info = self.label(inner, "", 8, SUB)

        def show(hid):  # 滑過哪個就顯示它的說明；平常顯示使用中的
            txt = ("所有房間都用這個頭" if hid == "KU100"
                   else "虛擬喇叭、錄音室、交叉饋送用這個頭；音樂廳用假人頭的")
            info.config(text=f"{head_name(hid)}{'（使用中）' if hid == cur else ''}　{txt}")

        for i, hid in enumerate(head_sets()):
            p = Pill(grid, self, "假人頭" if hid == "KU100" else hid, lambda h=hid: pick(h), size=10)
            p.set_selected(hid == cur)
            p.grid(row=i // 7, column=i % 7, padx=(0, px(4)), pady=(0, px(4)), sticky="we")
            p.bind("<Enter>", lambda _e, h=hid: show(h), add="+")
            p.bind("<Leave>", lambda _e: show(cur), add="+")
        info.pack(anchor="w")
        show(cur)
        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x", pady=(px(8), 0))
        Pill(row, self, "不知道選哪個？到「個人化」用測驗挑", lambda: (self.head_menu_close(), self.hf_dialog()),
             size=9).pack(side="right")
        pop.update_idletasks()
        lb = self.head_lbl
        x = min(lb.winfo_rootx(), pop.winfo_screenwidth() - pop.winfo_width() - px(8))
        y = lb.winfo_rooty() + lb.winfo_height() + px(4)
        if y + pop.winfo_height() > pop.winfo_screenheight() - px(48):
            y = max(px(8), lb.winfo_rooty() - pop.winfo_height() - px(4))
        pop.geometry(f"+{x}+{y}")
        pop.bind("<Escape>", lambda _e: self.head_menu_close())
        pop.bind("<FocusOut>", lambda e: e.widget is pop and self.head_menu_close())
        pop.focus_force()

    def head_menu_close(self):
        if self._head_pop:
            self._head_pop.destroy()
            self._head_pop, self._head_pop_t = None, time.time()

    # 頭型測驗：只聽前方、一次比兩個（配對比較：同一次配戴下比，耳機戴歪兩邊一樣歪，結果還是準）。
    # 先比各組代表（依前方的頻率響應＋兩耳時間差分好的組），再在贏的那組裡細比，最後重新戴耳機確認一次
    def head_intro(self):
        groups = head_groups_saved()
        self.pers_page("挑頭型（約 5 分鐘）",
                       "每題比兩個（A、B），按 1、2 或點 A、B 切換，想聽多久都可以。\n"
                       "聲音會在你前面「左前 → 正前 → 右前 → 正前」來回，像前面擺了三個喇叭；畫面上的點標出它應該在的位置。\n\n"
                       "只問一件事：哪一個比較像在你前面、跟眼睛差不多高、在頭外面？（不在頭頂、不在頭裡面）\n"
                       "兩個都不完美很正常，選比較接近的就好；真的分不出來就隨便選一個。\n\n"
                       "開始前先把耳機戴正：兩邊往下壓貼好、左右對稱。最後一題會請你重新戴一次再確認。\n\n"
                       f"不用播音樂：請先暫停音樂，音量照平常。{len(head_sets())} 個頭（KU100 假人頭＋SADIE II 的真人）"
                       f"分成 {len(groups)} 組，先比各組代表，再在贏的那組裡細比，大約 {self.head_total(groups)} 題。"
                       "測驗時暫時只留耳機校正，結束或中途離開都會自動還原。\n\n"
                       "老實說：頭型的差別不大（前方平均只差 2～3 dB，比重戴一次耳機的變化還小），"
                       "影響的是虛擬喇叭和殘響的音色、聲音的高度。選不出來就用假人頭。",
                       [("返回", self.pers_overview, False), ("開始", self.head_start, True)])
        self.err = self.label(self._hf_body, "", 9, ORANGE)
        self.err.pack(anchor="w")

    @staticmethod
    def head_total(groups):
        return len(groups) - 1 + round(sum(len(g) - 1 for g in groups) / len(groups)) + 1

    def head_start(self):
        try:
            import numpy as np
            sd, dev, sr = self.out_device()
        except ImportError:
            self.err.config(text="需要先安裝 numpy 和 sounddevice 這兩個套件。")
            return
        except Exception:
            self.err.config(text="找不到現在選的輸出裝置，請確認耳機或 DAC 有接上。")
            return
        groups = head_groups_saved()
        reps = [g[0] for g in groups]
        random.shuffle(reps)
        self._head = dict(np=np, sd=sd, dev=dev, sr=sr, groups=groups, stage=1, champ=reps[0], queue=reps[1:], last=None,
                          n=0, total=self.head_total(groups), clips={}, job=None, anim=None, t0=time.time())
        self._test = dict(style=[], hf=True, pref=True)  # 只留耳機校正：頭部量測是唯一的空間處理
        self.changed()
        self.head_advance()

    def head_advance(self):
        """下一題：目前贏的（冠軍）對下一個挑戰者；這一關比完就換下一關"""
        st = self._head
        if not st["queue"] and st["stage"] == 1:  # 代表比完 → 冠軍那一組的其他人
            grp = next(g for g in st["groups"] if st["champ"] in g)
            st["queue"] = [h for h in grp if h != st["champ"]]
            random.shuffle(st["queue"])
            st["stage"] = 2
        if st["queue"]:
            st["pair"] = random.sample([st["champ"], st["queue"].pop(0)], 2)
            self.head_page()
            return
        if st["stage"] == 2 and st["last"]:  # 最後確認：重新戴好耳機，冠軍跟最後一個對手再比一次
            st["stage"] = 3
            st["sd"].stop()
            self.pers_page("最後確認", "把耳機拿下來，重新戴好（兩邊往下壓貼合、左右對稱），再比最後一題。\n"
                           "換一次配戴還選同一個，就表示它真的比較適合你，不是剛好戴歪。",
                           [("放棄", self.pers_overview, False), ("戴好了", self.head_confirm, True)])
            return
        self.head_done(st["champ"])

    def head_confirm(self):
        st = self._head
        st["pair"] = random.sample([st["champ"], st["last"]], 2)
        self.head_page()

    def head_page(self):
        st, px = self._head, self.px
        stage = {1: "比較各組代表", 2: "在贏的那一組裡細比", 3: "重新戴好後確認"}[st["stage"]]
        body = self.pers_page(f"第 {st['n'] + 1} 題（大約 {max(st['total'], st['n'] + 1)} 題）　{stage}",
                              "A、B 哪一個比較像在你前面、跟眼睛差不多高、在頭外面？（不在頭頂、不在頭裡面）"
                              "按 1、2 切換，聽多久都可以。",
                              [("放棄", self.pers_overview, False), ("選目前這個", self.head_choose, True)])
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x")
        size = px(230)
        cv = st["cv"] = tk.Canvas(row, width=size, height=size, bg=PANEL, highlightthickness=0)
        cv.pack(side="left")
        c, R, r = size / 2, size * 0.38, size * 0.12
        cv.create_arc(c - R, c - R, c + R, c + R, start=50, extent=80, style="arc", outline=LINE, dash=(3, 4))  # 前方
        cv.create_oval(c - r, c - r, c + r, c + r, outline=SUB, width=2)  # 頭（從上往下看）
        cv.create_polygon(c - r * 0.3, c - r * 0.95, c, c - r * 1.35, c + r * 0.3, c - r * 0.95, fill=SUB)  # 鼻子＝前
        for s in (-1, 1):  # 耳朵
            cv.create_oval(c + s * r * 1.0 - r * 0.2, c - r * 0.3, c + s * r * 1.0 + r * 0.2, c + r * 0.3, outline=SUB)
        for txt, x, y in (("前（跟眼睛一樣高）", c, c - R - px(14)), ("左", c - R - px(14), c), ("右", c + R + px(14), c)):
            cv.create_text(x, y, text=txt, fill=SUB, font=(FONT, 9))
        st["dot"] = cv.create_oval(0, 0, 0, 0, fill=ACCENT, outline="")
        pills = tk.Frame(row, bg=PANEL)
        pills.pack(side="left", padx=px(16))
        st["pills"] = []
        for i in range(2):
            p = Pill(pills, self, "AB"[i], lambda i=i: self.head_pick(i), size=16)
            p.pack(side="top", pady=px(3), anchor="w")
            st["pills"].append(p)
            self._hf_win.bind(str(i + 1), lambda _e, i=i: self.head_pick(i))
        self.head_pick(0)
        if not st["anim"]:
            self.head_anim()
        self.center_on_root(self._hf_win)

    def head_pick(self, i):
        st = self._head
        st["cur"] = i
        for j, p in enumerate(st["pills"]):
            p.set_selected(j == i)
        hid = st["pair"][i]
        if hid not in st["clips"]:
            st["clips"][hid] = ring_clip(st["np"], hid, st["sr"])
        clip = st["clips"][hid]
        st["period"] = len(clip) / st["sr"]
        try:
            st["sd"].play(clip, st["sr"], device=st["dev"], loop=True)
        except Exception as e:
            self.pers_overview()
            messagebox.showerror("頭型", f"播放失敗：{e}", parent=self._hf_win)
            return
        st["t0"] = time.time()  # 從左前重新開始，畫面的點跟著重來

    def head_anim(self):
        """畫面上的點：現在這一聲應該在的位置（沒聲音時變淡）"""
        st = self._head
        if not st:
            return
        st["anim"] = self.root.after(40, self.head_anim)
        cv = st.get("cv")
        if not cv or not cv.winfo_exists() or "period" not in st:
            return
        t = (time.time() - st["t0"]) % st["period"]
        i = min(int(t // RING_STEP), len(RING_AZ) - 1)
        on = t < RING_STEP * len(RING_AZ) and t - i * RING_STEP < RING_ON
        size = int(cv["width"])
        c, R, d = size / 2, size * 0.38, self.px(9)
        az = math.radians(RING_AZ[i] if on else 0)
        x, y = c - R * math.sin(az), c - R * math.cos(az)
        cv.coords(st["dot"], x - d, y - d, x + d, y + d)
        cv.itemconfig(st["dot"], fill=ACCENT if on else LINE)

    def head_choose(self):
        st = self._head
        win, lose = st["pair"][st["cur"]], st["pair"][1 - st["cur"]]
        st["n"] += 1
        if st["stage"] == 3:
            self.head_done(win, win != st["champ"])
            return
        st["champ"], st["last"] = win, lose
        self.head_advance()

    def head_done(self, hid, changed=False):
        self.test_stop()
        note = "（重新戴好後選了另一個：這兩個很接近，用哪個都可以）" if changed else ""
        if hid == current_head():
            self.pers_page("挑選完成", f"你選的是：{head_name(hid)}{note}，跟現在用的一樣，不用改。",
                           [("完成", self.pers_overview, True)])
            return
        self.pers_page("挑選完成",
                       f"你選的是：{head_name(hid)}{note}（現在用的是 {head_name(current_head())}）。\n\n"
                       "改用的話，虛擬喇叭、錄音室殘響、交叉饋送馬上換成這個頭（音樂廳用假人頭的）。"
                       "之後可以點「交叉饋送」底下的「頭型 ▾」隨時換回來比較。",
                       [("先不要", self.pers_overview, False), ("改用", lambda: self.head_use(hid), True)])

    def head_use(self, hid):
        self.set_head(hid)
        self.toast(f"頭型：{head_name(hid)}")
        self.pers_overview()

    # 高頻校正
    def hf_intro(self):
        n = len(HF_BANDS) - 1
        self.pers_page("高頻校正（約 5 分鐘）",
                       "每一題輪流播兩個音高很接近的聲音，把第二個調到跟第一個一樣大聲就好"
                       "（拖滑桿或按左右鍵，好了按 Enter）。\n"
                       f"共 {2 * n} 題、分兩輪：第一輪從低往高，第二輪從高往低。滑桿沒有刻度，憑耳朵就好。\n\n"
                       "・請在安靜的房間測（開放式耳機外面的聲音會漏進來），先關掉風扇、冷氣這類一直響的聲音。\n"
                       "・兩輪中間會請你拿下耳機、照平常的方式重戴（入耳式重新塞好）：高頻會隨戴的位置改變，"
                       "只校正重戴後還在的部分。\n\n"
                       "開始前：先暫停音樂，音量維持平常聽歌的大小。測驗時暫時只留耳機校正，結束或中途離開都會自動還原。",
                       [("返回", self.pers_overview, False), ("開始", self.hf_start, True)])
        self.err = self.label(self._hf_body, "", 9, ORANGE)
        self.err.pack(anchor="w")

    def hf_start(self):
        try:
            import numpy as np
            sd, dev, sr = self.out_device()
        except ImportError:
            self.err.config(text="需要先安裝 numpy 和 sounddevice 這兩個套件。")
            return
        except Exception:
            self.err.config(text="找不到現在選的輸出裝置，請確認耳機或 DAC 有接上。")
            return
        n = len(HF_BANDS) - 1
        # 第一輪 (第一個聲音, 第二個聲音)＝(j, j+1) 由低往高；第二輪＝(j+1, j) 由高往低
        order = [(j, j + 1) for j in range(n)] + [(j + 1, j) for j in reversed(range(n))]
        self._hf = dict(np=np, sd=sd, dev=dev, sr=sr, order=order, k=0, up=[0.0] * n, down=[0.0] * n, job=None,
                        bursts=[hf_burst(np, fc, sr) for fc in HF_BANDS], reseated=False)
        self._test = dict(style=[], hf=False, pref=False)  # 只留耳機校正；等 Equalizer APO 讀進去再開始播
        self.changed()
        self.hf_page()

    def hf_page(self):
        st, px = self._hf, self.px
        n = len(st["order"])
        if st["k"] == n // 2 and not st["reseated"]:  # 兩輪中間：重戴耳機
            st["sd"].stop()

            def go():
                st["reseated"] = True
                self.hf_page()
            self.pers_page("第一輪完成", "請把耳機拿下來，再照你平常的方式戴回去，然後按「繼續」。\n"
                           "高頻會隨戴的位置改變，重戴一次才知道哪些是你耳朵本身的。",
                           [("放棄", self.pers_overview, False), ("繼續", go, True)])
            return
        st["off"] = random.uniform(-5, 5)  # 每題起點隨機：滑桿位置沒有意義，只能靠耳朵
        var = st["var"] = tk.DoubleVar(value=12.0)
        body = self.pers_page(f"第 {st['k'] + 1}／{n} 題　（第 {1 + st['k'] * 2 // n} 輪）",
                              "兩個聲音音高很接近，把第二個調到跟第一個一樣大聲。",
                              [("放棄", self.pers_overview, False),
                               ("下一題" if st["k"] + 1 < n else "完成", self.hf_next, True)])
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x")
        self.label(row, "小聲", 9, SUB).pack(side="left")
        sl = Slider(row, self, var, 0, 24, 0.5, 420, self.hf_play)
        sl.pack(side="left", padx=px(8))
        self.label(row, "大聲", 9, SUB).pack(side="left")
        win = self._hf_win
        win.bind("<Left>", lambda _e: sl.set(var.get() - 0.5))
        win.bind("<Right>", lambda _e: sl.set(var.get() + 0.5))
        st["job"] = self.root.after(900 if st["k"] in (0, n // 2) else 0, lambda: self.hf_play(True))
        win.focus_force()

    def hf_gain(self):
        return self._hf["var"].get() - 12 + self._hf["off"]

    def hf_play(self, now=False):
        st = self._hf
        if not st:
            return
        if st["job"]:
            self.root.after_cancel(st["job"])
        if not now:  # 拖動時等停下來再重播
            st["job"] = self.root.after(120, lambda: self.hf_play(True))
            return
        st["job"] = None
        a, b = st["order"][st["k"]]
        try:
            clip = hf_clip(st["np"], st["bursts"][a], st["bursts"][b], self.hf_gain(), sr=st["sr"])
            st["sd"].play(clip, st["sr"], device=st["dev"], loop=True)
        except Exception as e:
            self.pers_overview()
            messagebox.showerror("高頻校正", f"播放失敗：{e}", parent=self._hf_win)

    def hf_next(self):
        st = self._hf
        if not st:
            return
        if st["job"]:
            self.root.after_cancel(st["job"])
            st["job"] = None
        a, b = st["order"][st["k"]]
        (st["up"] if b > a else st["down"])[min(a, b)] = round(self.hf_gain(), 1)
        st["k"] += 1
        if st["k"] < len(st["order"]):
            self.hf_page()
            return
        st["sd"].stop()
        self._hf = None
        corr, filters, err = hf_analyze(st["up"], st["down"])
        self.hf_data = {"v": 2, "date": datetime.now().strftime("%Y-%m-%d"), "up": st["up"], "down": st["down"],
                        "corr": corr, "filters": [list(fl) for fl in filters], "spread": err}
        self.hf_on.set(True)
        self._test = None
        self.paint_hf()
        self.changed()
        peaks = [f"{fc / 1000:.1f} kHz {c:+.1f} dB" for fc, c in zip(HF_FREQS, corr) if abs(c) >= 1]
        text = ("你的耳朵在這些地方跟一般人不一樣，已經自動補正（＋是補強、－是減弱）：\n" + "、".join(peaks) if peaks
                else "你的耳朵跟一般人很接近，幾乎不用校正。")
        text += f"\n\n這次每一題的判斷誤差約 {err:g} dB"
        text += ("（很穩定）。" if err <= 1.5 else "，偏大：校正已經自動打折。可以改天在更安靜、精神好的時候再測一次。")
        self.pers_page("高頻校正完成", text + "\n\n已經套用到所有風格（只套用在這支耳機）。", [("完成", self.pers_overview, True)])
        self.center_on_root(self._hf_win)

    # 聲音偏好
    def pref_intro(self):
        self.pers_page("聲音偏好（約 8 分鐘）",
                       "先播一首你熟悉、常聽的歌（音質好一點的），音量照平常。\n\n"
                       "每一題有 A、B 兩種聲音，可以來回切換很多次（按 1、2 也可以），選你比較喜歡的那個。\n"
                       "兩個的音量已經對齊（大聲一點通常會被覺得比較好聽），名稱也藏起來。共 16 題，差別一題比一題小，"
                       "聽不出差別就憑感覺選。\n\n"
                       "測驗時暫時只留耳機校正（風格、殘響、分離度先拿掉），結束或中途離開都會自動還原。",
                       [("返回", self.pers_overview, False), ("開始", self.pref_start, True)])

    def pref_start(self):
        seq = [(d, s) for s in PREF_STEPS for d in ("bass", "treble")]
        self._pref = dict(seq=seq, k=0, est={"bass": 0.0, "treble": 0.0}, hist=[])
        self.pref_page()

    def pref_page(self):
        st, px = self._pref, self.px
        d, step = st["seq"][st["k"]]
        lo, hi = PREF_RANGE[d]
        vals = [max(lo, st["est"][d] - step), min(hi, st["est"][d] + step)]
        random.shuffle(vals)
        base = list(BASES[self.base.get()][1]) + self.hf_comp()

        def flt(v):
            e = dict(st["est"], **{d: v})
            return pref_filters(e["bass"], e["treble"])
        st["vals"], st["flts"] = vals, [flt(v) for v in vals]
        loud = [loudness_db(base + fl) for fl in st["flts"]]
        st["extra"] = [round(x - min(loud), 1) for x in loud]
        n = len(st["seq"])
        body = self.pers_page(f"第 {st['k'] + 1}／{n} 題", "來回切換 A、B，選你比較喜歡的那個。",
                              [("放棄", self.pers_overview, False), ("選目前這個", self.pref_choose, True)])
        row = tk.Frame(body, bg=PANEL)
        row.pack(anchor="w")
        st["pills"] = []
        for i in range(2):
            p = Pill(row, self, "AB"[i], lambda i=i: self.pref_pick(i), size=16)
            p.pack(side="left", padx=(0, px(8)))
            st["pills"].append(p)
            self._hf_win.bind(str(i + 1), lambda _e, i=i: self.pref_pick(i))
        self.pref_pick(0)
        self.center_on_root(self._hf_win)

    def pref_pick(self, i):
        st = self._pref
        st["cur"] = i
        for j, p in enumerate(st["pills"]):
            p.set_selected(j == i)
        self._test = dict(style=st["flts"][i], hf=True, pref=False, extra=st["extra"][i])
        self.changed()

    def pref_choose(self):
        st = self._pref
        d, step = st["seq"][st["k"]]
        v = st["vals"][st["cur"]]
        lo, hi = PREF_RANGE[d]
        st["est"][d] = min(hi, max(lo, st["est"][d] + (step / 2 if v > st["est"][d] else -step / 2)))
        st["hist"].append([d, step, v])
        st["k"] += 1
        if st["k"] < len(st["seq"]):
            self.pref_page()
            return
        b, t = round(st["est"]["bass"], 1), round(st["est"]["treble"], 1)
        self.pref_data = {"bass": b, "treble": t, "date": datetime.now().strftime("%Y-%m-%d"), "hist": st["hist"]}
        self.pref_on.set(True)
        self._pref, self._test = None, None
        self.paint_hf()
        self.changed()
        word = lambda x, name: (f"{name}比標準多 {x:g} dB" if x >= 1 else f"{name}比標準少 {-x:g} dB" if x <= -1
                                else f"{name}跟標準差不多")
        self.pers_page("聲音偏好完成",
                       f"你喜歡的聲音：{word(b, '低音')}、{word(t, '高音')}。\n\n"
                       "已經加到所有風格上（風格是在標準上調整，所以每個風格都會照你的喜好偏一點）。"
                       "可以在「個人化」隨時開關比較；換了常聽的音樂類型也可以重測。",
                       [("完成", self.pers_overview, True)])

    # ---------- 自我檢查：Equalizer APO 真的讀一次設定 ----------
    def run_selftest(self, show=False):
        if self._st_busy:
            return
        self._st_busy = True
        dev, cfg = find_device(self.dev_guid), self.cfg_dir

        def work():
            self._selftest = apo_selftest(cfg, dev) + (show,)
        threading.Thread(target=work, daemon=True).start()

    def selftest_done(self):
        """tick 裡呼叫：背景檢查做完了 → 更新狀態，需要就跳出結果"""
        res, self._selftest = self._selftest, None
        self._st_busy = False
        self.st_probs, cpu, show = res
        if show or self.st_probs:
            text = ("Equalizer APO 照這個裝置現在的格式真的讀了一次設定，沒有發現問題。" if not self.st_probs else
                    "發現這些問題：\n\n・" + "\n・".join(self.st_probs[:8]))
            if cpu is not None:
                text += f"\n\n全部效果即時運算約佔一個 CPU 核心的 {cpu:.0f}%（越低越不會爆音）。"
            (messagebox.showwarning if self.st_probs else messagebox.showinfo)("自我檢查", text, parent=self.root)

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
        self.passthrough.set(False)
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
        if self.dev_guid:
            self.profiles[self.dev_guid] = {"headphone": self.hp, "last": self.snapshot(), "loud": self.loud.get()}
        if self.hf_data and self.hf_key():
            self.hf_all[self.hf_key()] = {**self.hf_data, "on": self.hf_on.get()}
        data = {"presets": self.presets, "device": self.dev_guid, "follow": self.follow.get(), "profiles": self.profiles,
                "sep": int(self.sep_level.get()), "hf": self.hf_all, "head": current_head(),
                "pref": {**self.pref_data, "on": self.pref_on.get()} if self.pref_data else {}}
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
            self.apply_snap(p)

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
    else:  # 只能開一個：兩個同時開會互相蓋掉設定 → 已經開著就把那個叫到前面
        _single = ctypes.windll.kernel32.CreateMutexW(None, False, "HeadphoneTuner_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            _hwnd = ctypes.windll.user32.FindWindowW(None, "耳機調音台")
            if _hwnd:
                ctypes.windll.user32.ShowWindow(_hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(_hwnd)
            sys.exit(0)
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
