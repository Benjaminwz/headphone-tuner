"""殘響模擬 v5：用顯示卡（GPU）在真實形狀的房間裡做聲學模擬，產生調音台用的殘響檔。
執行：python tools/殘響模擬.py [房間…] [--quick]（--quick＝聲線少、快速試算）。要 PyTorch，有 NVIDIA 顯示卡才跑得快；
調音台用 studio、hall_front、hall_mid（club、opera 是備用的房間）

做法（建築聲學軟體的「混合法」：Vorländer《Auralization》2008；ODEON、RAVEN 的架構）
1. 房間形狀：平面多邊形組成（陽台、欄杆、舞台、包廂、窗、吸音板…），每一面有自己的材質（9 個八度頻段的吸音、散射係數）
   - 錄音室：ITU-R BS.1116 聆聽室（7×5×2.8 m）＋第一反射點吸音板、天花板吸音雲、後牆擴散板
   - 俱樂部：Adelman-Larsen 2010 調查的中小型場地（2,688 m³）＋舞台、吧台、吸音簾
   - 歌劇院：維也納國家歌劇院（Beranek 2004：10,665 m³）→ 馬蹄形觀眾席、包廂牆、鏡框台口後面的舞台塔（耦合空間）
   - 音樂廳：維也納金色大廳（Beranek 2004：15,000 m³，寬 19.8、高 17.75 m）→ 舞台、三面陽台與欄杆、上方窗戶、雕飾天花板
2. 早期反射：鏡像聲源法（Allen & Berkley 1979；多邊形版 Borish 1984, JASA），做到 3–5 階，每一條路徑檢查有沒有被擋住；
   每道反射有自己的時間、方向、各頻段吸音、聲源指向性、空氣吸收
3. 後段：GPU 聲線追蹤，每個聲源 3,355 萬條聲線打在三角面上；依散射係數決定鏡面或 Lambert 漫射（各頻段不同，用權重處理）；
   空氣吸收照 ISO 9613-1（20 °C、50%）；鏡像法已經算過的路徑不重複；記錄各頻段能量和到達方向（128 個方向）
   → 依房間的回聲密度 4πc³t²/V（Kuttruff）產生隨機正負的脈衝，每個脈衝依追蹤出的方向分佈決定從哪裡來
4. 兩耳：剛性球頭的精確解（Duda & Martens 1998, JASA；耳朵在 ±100°），以正前方為基準；
   早期反射、後段的每個方向都經過這個頭部模型 → 兩耳差異、兩耳相關性都是算出來的
5. 聲源指向性：喇叭、人聲近似成剛性球上的點聲源（互易原理，跟頭部模型同一個公式）；樂團當成全指向
6. 吸音校正：各頻段整體縮放，讓殘響時間對上調音台原本的數據（Beranek、BS.1116、Adelman-Larsen）；空氣吸收不縮放
7. 檢查：ISO 3382-1 的 EDT、T30、C80、D50、側向能量比 LF、兩耳相關 IACC；錄音室另外檢查 BS.1116「15 ms 內的反射至少低 10 dB」
輸出：「殘響」資料夾裡的 <房間>.npy（用 96 kHz 算、存成 48 kHz、4 聲道、只有殘響、每個聲源兩耳總能量＝1；只留 20 Hz–20 kHz）、結果.json
調音台再依原本的直達/殘響比縮放，所以殘響大小不變
"""
import json
import math
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 專案資料夾（這個檔在 tools 裡）
OUT = os.path.join(HERE, "殘響")
C = 343.2                       # 20 °C 的音速
FS = 96000
SAVE_FS = 48000                 # 存檔的取樣率：只有 20 kHz 以下，48 kHz 就完整保存（檔案小一半）
DT, DT_DIR = 0.001, 0.01        # 能量每 1 ms 一格、方向分佈每 10 ms 一格
BANDS = np.array([63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000], float)
NB = len(BANDS)
A_HEAD = 0.0875                 # 頭的半徑（Duda & Martens 1998）
EAR = math.radians(100)         # 耳朵在正前方左右 100°（稍微偏後）
N_DIR = 128
QUICK = "--quick" in sys.argv
if QUICK:  # 試算不蓋掉正式的殘響檔
    OUT = os.path.join(os.environ.get("TEMP", HERE), "殘響試算")
RAYS = 1 << (20 if QUICK else 25)
CAL_RAYS = 1 << (19 if QUICK else 23)
CHUNK = 1 << 19
DEV = "cuda" if torch.cuda.is_available() else "cpu"

# 材質：吸音係數、散射係數（63 Hz–16 kHz）、是否只有散射（觀眾、樂團、人群：貼著它們的反射會被吸掉、打散，
# 座椅凹陷效應 Schultz & Watters 1964）。數值是典型值（Vorländer 2008 附錄、Kuttruff《Room Acoustics》），
# 之後各頻段整體校正到目標殘響時間，所以重點是「哪裡吸、哪裡反射、哪裡打散」
MAT = {
    "plaster":  ([.01, .01, .02, .02, .03, .04, .05, .05, .05], [.05, .05, .10, .15, .20, .25, .30, .30, .30], False),
    "wood":     ([.15, .15, .11, .10, .07, .06, .07, .07, .07], [.10, .10, .15, .20, .25, .30, .35, .35, .35], False),
    "ornate":   ([.02, .03, .04, .05, .06, .07, .08, .08, .08], [.20, .30, .50, .70, .80, .85, .90, .90, .90], False),
    "glass":    ([.35, .35, .25, .18, .12, .07, .04, .04, .04], [.05, .05, .05, .05, .05, .05, .05, .05, .05], False),
    "brick":    ([.02, .02, .03, .03, .04, .05, .07, .07, .07], [.10, .15, .25, .35, .45, .50, .50, .50, .50], False),
    "industry": ([.05, .10, .10, .10, .10, .10, .10, .10, .10], [.20, .30, .40, .50, .60, .60, .60, .60, .60], False),
    "carpet":   ([.02, .05, .08, .20, .35, .50, .60, .65, .65], [.05, .05, .10, .10, .15, .20, .20, .20, .20], False),
    "absorber": ([.15, .30, .70, .95, .95, .95, .95, .95, .95], [.05, .05, .10, .10, .10, .10, .10, .10, .10], False),
    "diffuser": ([.05, .10, .15, .15, .15, .15, .15, .15, .15], [.05, .10, .40, .80, .90, .90, .90, .90, .90], False),
    "curtain":  ([.05, .07, .30, .50, .70, .70, .65, .65, .65], [.10, .10, .20, .30, .40, .40, .40, .40, .40], False),
    "boxes":    ([.30, .40, .55, .65, .70, .70, .70, .70, .70], [.40, .50, .60, .70, .70, .70, .70, .70, .70], False),
    "scenery":  ([.20, .30, .40, .50, .55, .55, .55, .55, .55], [.50, .60, .70, .70, .70, .70, .70, .70, .70], False),
    "seats":    ([.40, .50, .70, .80, .85, .85, .85, .85, .85], [1] * 9, True),
    "crowd":    ([.15, .25, .45, .65, .80, .85, .85, .85, .85], [1] * 9, True),
    "orchestra": ([.20, .25, .30, .35, .40, .40, .40, .40, .40], [1] * 9, True),
}
MAT_NAMES = list(MAT)


def rect(axis, c, u0, u1, v0, v1, mat):
    """跟座標軸垂直的長方形：axis 那一軸＝c，另外兩軸（照 x、y、z 順序）範圍 u0–u1、v0–v1"""
    o = [i for i in range(3) if i != axis]
    pts = []
    for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
        p = [0.0, 0.0, 0.0]
        p[axis], p[o[0]], p[o[1]] = c, u, v
        pts.append(p)
    return np.array(pts), mat


def shell(L, W, H, x0, x1, y0, y1, floor, ceil):
    return [rect(0, 0, 0, W, 0, H, x0), rect(0, L, 0, W, 0, H, x1), rect(1, 0, 0, L, 0, H, y0),
            rect(1, W, 0, L, 0, H, y1), rect(2, 0, 0, L, 0, W, floor), rect(2, H, 0, L, 0, W, ceil)]


def studio():
    L, W, H = 7.0, 5.0, 2.8
    P = shell(L, W, H, "plaster", "plaster", "plaster", "plaster", "carpet", "plaster")
    P += [rect(0, 0.03, 0.4, W - 0.4, 0.3, 2.5, "absorber"),                # 喇叭後面的前牆
          rect(1, 0.03, 1.9, 4.1, 0.5, 1.9, "absorber"),                    # 側牆第一反射點（左右喇叭打到側牆的點）
          rect(1, W - 0.03, 1.9, 4.1, 0.5, 1.9, "absorber"),
          rect(2, H - 0.2, 1.6, 4.6, 1.0, 4.0, "absorber"),                 # 天花板第一反射點的吸音雲
          rect(2, 0.02, 2.4, 4.0, 1.4, 3.6, "absorber"),                    # 喇叭和聽者之間的厚地毯（地板反射）
          rect(0, L - 0.03, 0.5, W - 0.5, 0.4, 2.4, "diffuser")]            # 後牆擴散板
    # 兩個喇叭跟聽者成正三角形（底邊 2.4 m，±30°），高度跟耳朵一樣 1.2 m（BS.1116）
    return dict(polys=P, src=[(2.12, 1.3, 1.2), (2.12, 3.7, 1.2)], rcv=(4.2, 2.5, 1.2), src_a=0.12,
                rt=(0.25, 1.0, 0.9), order=5)


def club():
    L, W, H = 24.0, 16.0, 7.0
    P = shell(L, W, H, "brick", "brick", "brick", "brick", "crowd", "industry")
    P += [rect(2, 1.0, 0, 5.0, 0, W, "wood"), rect(0, 5.0, 0, W, 0, 1.0, "wood"),        # 舞台
          rect(2, 1.1, 21.5, L, 2, 14, "wood"), rect(0, 21.5, 2, 14, 0, 1.1, "wood"),     # 吧台
          rect(1, 2, 21.5, L, 0, 1.1, "wood"), rect(1, 14, 21.5, L, 0, 1.1, "wood"),
          rect(1, 0.05, 7, 19, 2.5, 6.0, "curtain"), rect(1, W - 0.05, 7, 19, 2.5, 6.0, "curtain")]  # 側牆吸音簾
    # 舞台兩側 PA 喇叭離聽者 12 m，站著聽；PA 箱比較大 → 球半徑 0.35 m，指向性比較強
    return dict(polys=P, src=[(3.0, 4.0, 3.0), (3.0, 12.0, 3.0)], rcv=(15.0, 8.0, 1.6), src_a=0.35,
                rt=(0.8, 0.9, 0.8), order=4)


def opera():
    H, cy = 19.5, 10.5
    # 觀眾席平面（從上面看）：台口寬 16 m → 4 m 內張開到 21 m → 直到 18 m → 後面半圓（馬蹄形）
    plan = [(0, 2.5), (4, 0), (18, 0)]
    plan += [(18 + 10.5 * math.sin(a), cy - 10.5 * math.cos(a)) for a in np.linspace(0, math.pi, 9)[1:-1]]
    plan += [(18, 21), (4, 21), (0, 18.5)]
    P = []
    for (x0, y0), (x1, y1) in zip(plan, plan[1:]):
        for z0, z1, m in ((0, 2, "wood"), (2, 16, "boxes"), (16, H, "plaster")):  # 下面木牆、4 層包廂、上面
            P.append((np.array([(x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)], float), m))
    P.append((np.array([(x, y, H) for x, y in plan], float), "ornate"))   # 天花板
    P.append((np.array([(x, y, 0) for x, y in plan], float), "seats"))    # 觀眾席
    # 台口（x＝0 的牆，開口寬 15 m、從舞台面 1 m 到 13 m）
    P += [rect(0, 0, -4, 3, 0, 30, "plaster"), rect(0, 0, 18, 25, 0, 30, "plaster"),
          rect(0, 0, 3, 18, 0, 1, "wood"), rect(0, 0, 3, 18, 13, 30, "plaster")]
    # 舞台塔：20×29×30 m，布景、幕會吸音也會打散
    P += [rect(0, -20, -4, 25, 0, 30, "scenery"), rect(1, -4, -20, 0, 0, 30, "scenery"),
          rect(1, 25, -20, 0, 0, 30, "scenery"), rect(2, 30, -20, 0, -4, 25, "scenery"),
          rect(2, 1.0, -20, 0, -4, 25, "wood")]
    # 歌手在台口後 3 m、左右各 3 m，嘴巴高 1.7 m；人頭 → 球半徑 0.0875 m
    return dict(polys=P, src=[(-3.0, 7.5, 2.7), (-3.0, 13.5, 2.7)], rcv=(20.0, cy, 1.2), src_a=A_HEAD,
                rt=(1.3, 1.1, 0.8), order=3)


def hall(rcv):
    L, W, H = 42.7, 19.8, 17.75
    P = [rect(0, 0, 0, W, 0, H, "ornate"),            # 舞台後面：管風琴、合唱席
         rect(0, L, 0, W, 0, H, "ornate"),
         rect(1, 0, 0, L, 0, 6.5, "wood"), rect(1, 0, 0, L, 6.5, H, "ornate"),
         rect(1, W, 0, L, 0, 6.5, "wood"), rect(1, W, 0, L, 6.5, H, "ornate"),
         rect(2, 0, 0, L, 0, W, "seats"),
         rect(2, H, 0, L, 0, W, "ornate")]             # 有格子、雕飾的天花板
    P += [rect(2, 1.0, 0, 9, 0, W, "orchestra"), rect(0, 9, 0, W, 0, 1.0, "wood")]  # 舞台（上面是樂團）
    for y0, y1, front in ((0, 2.6, 2.6), (W - 2.6, W, W - 2.6)):   # 兩側陽台（深 2.6 m、離地 6.5 m）＋欄杆
        P += [rect(2, 7.0, 9, 39, y0, y1, "seats"), rect(2, 6.5, 9, 39, y0, y1, "ornate"),
              rect(1, front, 9, 39, 6.5, 8.0, "ornate"), rect(0, 9, y0, y1, 6.5, 8.0, "ornate")]
    P += [rect(2, 7.0, 39, L, 0, W, "seats"), rect(2, 6.5, 39, L, 0, W, "ornate"),          # 後面陽台
          rect(0, 39, 2.6, W - 2.6, 6.5, 8.0, "ornate")]
    for x in (12, 19, 26, 33):                                     # 上方窗戶
        P += [rect(1, 0.03, x, x + 3, 12, 15.5, "glass"), rect(1, W - 0.03, x, x + 3, 12, 15.5, "glass")]
    # 樂團在舞台左右各 5 m、高 1.5 m（全指向）
    return dict(polys=P, src=[(5.0, 4.9, 2.5), (5.0, 14.9, 2.5)], rcv=rcv, src_a=None, rt=(2.0, 1.2, 0.75), order=4)


SCENES = {"studio": studio, "club": club, "opera": opera,
          "hall_front": lambda: hall((16.0, 9.9, 1.2)), "hall_mid": lambda: hall((26.0, 9.9, 1.2))}


def target_rt(rt, br, tr):
    """各頻段的目標殘響時間（跟原本一樣：500 Hz 以下乘低頻倍數、4 kHz 乘高頻倍數、8 kHz 以上再乘 0.6）"""
    return np.array([rt * br] * 3 + [rt] * 3 + [rt * tr] + [rt * tr * 0.6] * 2)


def air_db_per_m(f, T=293.15, rh=50.0):
    """ISO 9613-1 空氣吸收（dB/m）"""
    pa = pr = 101.325
    T0, T01 = 293.15, 273.16
    h = rh * 10 ** (-6.8346 * (T01 / T) ** 1.261 + 4.6151) * pr / pa
    frO = pa / pr * (24 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    frN = pa / pr * (T / T0) ** -0.5 * (9 + 280 * h * math.exp(-4.170 * ((T / T0) ** (-1 / 3) - 1)))
    return 8.686 * f ** 2 * (1.84e-11 * (pa / pr) ** -1 * (T / T0) ** 0.5 + (T / T0) ** -2.5 * (
        0.01275 * math.exp(-2239.1 / T) / (frO + f ** 2 / frO) + 0.1068 * math.exp(-3352.0 / T) / (frN + f ** 2 / frN)))


M_AIR = air_db_per_m(BANDS) / (10 * math.log10(math.e))  # 能量衰減（1/m）


def sphere(f, theta, a):
    """剛性球（半徑 a）表面一點，平面波從 theta 角來（0＝正對）的頻率響應：Duda & Martens 1998 的級數解。
    用 numpy 的時間慣例（延遲＝e^{-j2πfτ}）；互易原理：也等於球面上點聲源往 theta 方向的輻射"""
    f = np.asarray(f, float)
    H = np.ones((len(theta), len(f)), complex)
    x = 2 * np.pi * f * a / C
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


def smooth_third(mag):
    """1/3 八度平滑（能量平均）"""
    cs = np.concatenate([[0], np.cumsum(mag ** 2)])
    i = np.arange(len(mag))
    lo = np.floor(i / 2 ** (1 / 6)).astype(int)
    hi = np.minimum(np.ceil(i * 2 ** (1 / 6)).astype(int) + 1, len(mag))
    return np.sqrt((cs[hi] - cs[lo]) / np.maximum(hi - lo, 1))


def hrir_table():
    """0–180°（從耳朵算）每 1° 的頭部脈衝響應，以「正前方的聲音」為基準（正前方＝原音，不改音色）"""
    n = 8192
    f = np.fft.rfftfreq(n, 1 / FS)
    H = sphere(f, np.radians(np.arange(181)), A_HEAD)
    front = H[100]
    rel = H * (np.conj(front) / np.maximum(np.abs(front), 1e-12)) / np.maximum(smooth_third(np.abs(front)), 1e-6)
    t_pre = 0.0015
    h = np.fft.irfft(rel * np.exp(-2j * np.pi * f * t_pre), n)
    keep = int(FS * 0.0045)
    win = np.ones(keep)
    q = keep // 4
    win[keep - q:] = np.cos(np.linspace(0, np.pi / 2, q)) ** 2
    return h[:, :keep] * win, t_pre


def directivity(a):
    """聲源指向性（181 個角度 × 9 頻段，正對聽者＝1）：剛性球上的點聲源；None＝全指向"""
    if a is None:
        return np.ones((181, NB))
    fs_ = np.concatenate([BANDS * 2 ** (-1 / 3), BANDS, BANDS * 2 ** (1 / 3)])
    P = np.abs(sphere(fs_, np.radians(np.arange(181)), a)) ** 2
    P = P / P[:1]
    return P.reshape(181, 3, NB).mean(1)


def band_weights(f):
    """9 個頻段的分頻權重（相鄰頻段在 log 頻率上交叉淡入淡出，加起來剛好是 1）"""
    lf, lc = np.log2(np.maximum(f, 1e-9)), np.log2(BANDS)
    W = np.ones((NB, len(f)))
    for b in range(NB):
        if b > 0:
            x = np.clip((lf - lc[b - 1]) / (lc[b] - lc[b - 1]), 0, 1)
            W[b] *= np.where(lf < lc[b], np.sin(np.pi / 2 * x) ** 2, 1)
        if b < NB - 1:
            x = np.clip((lf - lc[b]) / (lc[b + 1] - lc[b]), 0, 1)
            W[b] *= np.where(lf > lc[b], np.cos(np.pi / 2 * x) ** 2, 1)
    return W


def fib_dirs(n):
    i = np.arange(n) + 0.5
    z = 1 - 2 * i / n
    r = np.sqrt(1 - z * z)
    ph = i * math.pi * (3 - math.sqrt(5))
    return np.stack([r * np.cos(ph), r * np.sin(ph), z], 1)


class Geometry:
    def __init__(self, scene):
        polys = scene["polys"]
        K = max(len(v) for v, _m in polys)
        self.np_ = len(polys)
        pv = np.zeros((self.np_, K, 3))
        tris, tpoly = [], []
        for i, (v, _m) in enumerate(polys):
            pv[i, :len(v)] = v
            pv[i, len(v):] = v[-1]
            for k in range(1, len(v) - 1):
                tris.append((v[0], v[k], v[k + 1]))
                tpoly.append(i)
        pn = np.cross(pv[:, 1] - pv[:, 0], pv[:, 2] - pv[:, 0])
        pn /= np.linalg.norm(pn, axis=1, keepdims=True)
        self.pmat = np.array([MAT_NAMES.index(m) for _v, m in polys])
        tris = np.array(tris)
        self.pv = torch.tensor(pv, device=DEV)
        self.pn = torch.tensor(pn, device=DEV)
        self.tv0 = torch.tensor(tris[:, 0], device=DEV, dtype=torch.float32)
        self.te1 = torch.tensor(tris[:, 1] - tris[:, 0], device=DEV, dtype=torch.float32)
        self.te2 = torch.tensor(tris[:, 2] - tris[:, 0], device=DEV, dtype=torch.float32)
        self.tpoly = torch.tensor(tpoly, device=DEV)
        self.tn = self.pn[self.tpoly].float()
        self.tmat = torch.tensor(self.pmat, device=DEV)[self.tpoly]
        self.aud = np.array([MAT[m][2] for m in MAT_NAMES])

    def hit(self, o, d, tmax=None, exclude=None):
        """光線（或線段）跟所有三角面的第一個交點 → (距離, 三角面編號)；分批算避免顯示卡記憶體不夠"""
        outs_t, outs_i = [], []
        step = max(1, (1 << 24) // max(1, self.tv0.shape[0]))
        for s in range(0, o.shape[0], step):
            oo, dd = o[s:s + step], d[s:s + step]
            p = torch.linalg.cross(dd[:, None, :].expand(-1, self.te2.shape[0], -1),
                                   self.te2[None].expand(dd.shape[0], -1, -1), dim=2)
            det = (self.te1[None] * p).sum(-1)
            inv = 1 / torch.where(det.abs() > 1e-12, det, torch.ones_like(det))
            tv = oo[:, None, :] - self.tv0[None]
            u = (tv * p).sum(-1) * inv
            q = torch.linalg.cross(tv, self.te1[None].expand_as(tv), dim=2)
            v = (dd[:, None, :] * q).sum(-1) * inv
            t = (self.te2[None] * q).sum(-1) * inv
            ok = (det.abs() > 1e-12) & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 1e-5)
            if tmax is not None:
                ok &= t < tmax
            if exclude is not None:
                ok &= ~exclude[s:s + step]
            t = torch.where(ok, t, torch.full_like(t, float("inf")))
            tm, ti = t.min(1)
            outs_t.append(tm)
            outs_i.append(ti)
        return torch.cat(outs_t), torch.cat(outs_i)


def lambert(nrm, g):
    k = nrm.shape[0]
    u1 = torch.rand(k, generator=g, device=DEV)
    ph = 2 * math.pi * torch.rand(k, generator=g, device=DEV)
    a = torch.where((nrm[:, :1].abs() < 0.9), torch.tensor([[1.0, 0, 0]], device=DEV),
                    torch.tensor([[0, 1.0, 0]], device=DEV))
    t1 = torch.linalg.cross(nrm, a, dim=1)
    t1 = t1 / t1.norm(dim=1, keepdim=True)
    t2 = torch.linalg.cross(nrm, t1, dim=1)
    st = torch.sqrt(u1)[:, None]
    return torch.sqrt(1 - u1)[:, None] * nrm + st * torch.cos(ph)[:, None] * t1 + st * torch.sin(ph)[:, None] * t2


def trace(G, scene, alpha, src, n_rays, t_end, ism_order, rec_all, seed, dirs, dtab):
    """GPU 聲線追蹤 → (各頻段每 1 ms 的能量, 各頻段每 10 ms 各方向的能量, 直達聲檢查, 漏掉的聲線數)；能量都相對直達聲"""
    g = torch.Generator(device=DEV).manual_seed(seed)
    S = torch.tensor(src, device=DEV, dtype=torch.float32)
    R = torch.tensor(scene["rcv"], device=DEV, dtype=torch.float32)
    d0 = float((R - S).norm())
    axis = (R - S) / d0
    r = 0.1 * (scene["V"] / 100) ** (1 / 3)
    nb, ncb = int(t_end / DT) + 1, int(t_end / DT_DIR) + 1
    hf = torch.zeros(NB, nb, device=DEV, dtype=torch.float64)
    hd = torch.zeros(NB, ncb * N_DIR, device=DEV, dtype=torch.float64)
    mair = torch.tensor(M_AIR, device=DEV, dtype=torch.float32)
    al = torch.tensor(alpha, device=DEV, dtype=torch.float32)
    sc = torch.tensor(np.array([MAT[m][1] for m in MAT_NAMES]), device=DEV, dtype=torch.float32)
    aud = torch.tensor(G.aud, device=DEV)
    sc[aud] = 1.0
    p_sc = torch.where(aud, torch.ones(len(MAT_NAMES), device=DEV), sc.mean(1).clamp(0.02, 0.98))
    dt_ = torch.tensor(dtab, device=DEV, dtype=torch.float32)
    dirs_t = torch.tensor(dirs, device=DEV, dtype=torch.float32)
    direct, leaks = 0.0, 0
    for c0 in range(0, n_rays, CHUNK):
        n = min(CHUNK, n_rays - c0)
        d = torch.randn(n, 3, generator=g, device=DEV)
        d /= d.norm(dim=1, keepdim=True)
        th = torch.rad2deg(torch.arccos((d @ axis).clamp(-1, 1))).round().long()
        E = dt_[th] / n_rays
        pos = S.repeat(n, 1)
        dist = torch.zeros(n, device=DEV)
        order = torch.zeros(n, device=DEV, dtype=torch.long)
        spec = torch.ones(n, device=DEV, dtype=torch.bool)
        while pos.shape[0]:
            k = pos.shape[0]
            tmin, ti = G.hit(pos, d)
            esc = torch.isinf(tmin)
            leaks += int(esc.sum())
            tmin = torch.where(esc, torch.zeros_like(tmin), tmin)
            w = R - pos
            proj = (w * d).sum(1)
            d2 = (w * w).sum(1) - proj ** 2
            hit = (proj > 0) & (proj < tmin) & (d2 < r * r) & ~esc
            if hit.any():
                chord = 2 * torch.sqrt(r * r - d2[hit])
                e = E[hit] * torch.exp(-mair[None] * proj[hit, None]) * chord[:, None]
                o = order[hit]
                is_dir = o == 0
                if is_dir.any():
                    direct += float(e[is_dir, 4].sum())
                keep = ~is_dir & (rec_all | ~(spec[hit] & (o <= ism_order)))
                if keep.any():
                    t = (dist[hit] + proj[hit])[keep] / C
                    ek = e[keep].T.double()
                    hf.index_add_(1, (t / DT).long().clamp(max=nb - 1), ek)
                    dc = ((-d[hit][keep]) @ dirs_t.T).argmax(1)
                    hd.index_add_(1, (t / DT_DIR).long().clamp(max=ncb - 1) * N_DIR + dc, ek)
            pos = pos + d * tmin[:, None]
            dist = dist + tmin
            E = E * torch.exp(-mair[None] * tmin[:, None])
            nrm = G.tn[ti]
            nrm = torch.where(((nrm * d).sum(1) > 0)[:, None], -nrm, nrm)   # 朝向聲線來的那一側
            m = G.tmat[ti]
            E = E * (1 - al[m])
            s_b, pp = sc[m], p_sc[m]
            diffuse = torch.rand(k, generator=g, device=DEV) < pp
            E = E * torch.where(diffuse[:, None], s_b / pp[:, None],
                                (1 - s_b) / (1 - pp).clamp(min=1e-6)[:, None])  # 各頻段散射不同：用權重修正
            sd = d - 2 * (d * nrm).sum(1, keepdim=True) * nrm
            d = torch.where(diffuse[:, None], lambert(nrm, g), sd)
            d = d / d.norm(dim=1, keepdim=True)
            spec &= ~diffuse
            order += 1
            pos = pos + nrm * 1e-4
            alive = ~esc & (dist / C < t_end) & (E.max(1).values > 1e-9 / n_rays)
            if not bool(alive.all()):
                idx = alive.nonzero().squeeze(1)
                pos, d, E, dist, order, spec = pos[idx], d[idx], E[idx], dist[idx], order[idx], spec[idx]
    scale = torch.tensor(3 * d0 ** 2 / r ** 3 * np.exp(M_AIR * d0), device=DEV)[:, None]
    direct *= 3 * d0 ** 2 / r ** 3 * math.exp(M_AIR[4] * d0)
    return (hf * scale).cpu().numpy(), (hd * scale).cpu().numpy().reshape(NB, ncb, N_DIR), direct, leaks


def mirror(p, n, v0):
    return p - 2 * ((p - v0) * n).sum(-1, keepdim=True) * n


def inside(G, X, pi):
    v = G.pv[pi]
    e = torch.roll(v, -1, 1) - v
    c = torch.linalg.cross(e, X[:, None, :] - v, dim=2)
    return ((c * G.pn[pi][:, None, :]).sum(-1) >= -1e-7).all(1)


def ism(G, scene, alpha, src, order, dtab):
    """鏡像聲源（多邊形）：所有 1…order 階、沒被擋住的鏡面反射路徑 → [(延遲, 到達方向, 9 頻段振幅, 階數)]"""
    S = torch.tensor(src, device=DEV, dtype=torch.float64)
    R = torch.tensor(scene["rcv"], device=DEV, dtype=torch.float64)
    d0 = float((R - S).norm())
    axis = (R - S) / d0
    spec_polys = torch.tensor([i for i in range(G.np_) if not G.aud[G.pmat[i]]], device=DEV)
    sc = np.array([MAT[m][1] for m in MAT_NAMES])
    refl = torch.tensor(np.sqrt((1 - alpha) * (1 - sc)), device=DEV)            # (材質, 頻段)
    pm = torch.tensor(G.pmat, device=DEV)
    mair = torch.tensor(M_AIR, device=DEV)
    seq = spec_polys[:, None]
    chain = mirror(S[None], G.pn[spec_polys], G.pv[spec_polys, 0])[:, None, :]
    out = []
    for k in range(1, order + 1):
        for s0 in range(0, seq.shape[0], 1 << 15):
            sq, ch = seq[s0:s0 + (1 << 15)], chain[s0:s0 + (1 << 15)]
            M = sq.shape[0]
            X = R.expand(M, 3).clone()
            ok = torch.ones(M, dtype=torch.bool, device=DEV)
            pts = [None] * k
            for lvl in reversed(range(k)):
                tgt, p = ch[:, lvl], sq[:, lvl]
                n, v0 = G.pn[p], G.pv[p, 0]
                dv = tgt - X
                den = (dv * n).sum(1)
                t = ((v0 - X) * n).sum(1) / torch.where(den.abs() > 1e-12, den, torch.ones_like(den))
                ok &= (den.abs() > 1e-12) & (t > 1e-7) & (t < 1 - 1e-7)
                X = X + t[:, None] * dv
                ok &= inside(G, X, p)
                pts[lvl] = X
            idx = ok.nonzero().squeeze(1)
            if not len(idx):
                continue
            ends = [S.expand(len(idx), 3)] + [pt[idx] for pt in pts] + [R.expand(len(idx), 3)]
            polys = [None] + [sq[idx, i] for i in range(k)] + [None]
            free = torch.ones(len(idx), dtype=torch.bool, device=DEV)
            for a_, b_, pa, pb in zip(ends, ends[1:], polys, polys[1:]):
                ex = torch.zeros(len(idx), G.tpoly.shape[0], dtype=torch.bool, device=DEV)
                if pa is not None:
                    ex |= G.tpoly[None] == pa[:, None]
                if pb is not None:
                    ex |= G.tpoly[None] == pb[:, None]
                tm, _ = G.hit(a_.float(), (b_ - a_).float(), tmax=1 - 1e-5, exclude=ex)
                free &= torch.isinf(tm)
            if not bool(free.any()):
                continue
            idx2 = idx[free]
            first, last = pts[0][idx2], pts[-1][idx2]
            Ltot = (ch[idx2, -1] - R).norm(dim=1)
            arrive = (last - R) / (last - R).norm(dim=1, keepdim=True)
            emit = (first - S) / (first - S).norm(dim=1, keepdim=True)
            th = torch.rad2deg(torch.arccos((emit @ axis).clamp(-1, 1))).round().long().cpu().numpy()
            amp = torch.ones(len(idx2), NB, device=DEV, dtype=torch.float64)
            for i in range(k):
                amp = amp * refl[pm[sq[idx2, i]]]
            amp = amp * (d0 / Ltot)[:, None] * torch.exp(-mair[None] * (Ltot - d0)[:, None] / 2)
            amp = amp.cpu().numpy() * np.sqrt(dtab[th])
            delay = ((Ltot - d0) / C).cpu().numpy()
            arrive = arrive.cpu().numpy()
            out += [(float(delay[i]), arrive[i], amp[i], k) for i in range(len(idx2))]
        if k < order:   # 再多反射一次（不連續碰同一面）
            Ms = seq.shape[0]
            q = spec_polys[None].expand(Ms, -1)
            mi, qi = (q != seq[:, -1:]).nonzero(as_tuple=True)
            qq = q[mi, qi]
            seq = torch.cat([seq[mi], qq[:, None]], 1)
            chain = torch.cat([chain[mi], mirror(chain[mi, -1], G.pn[qq], G.pv[qq, 0])[:, None]], 1)
    return out


def smooth(e):
    """聲線數有限，後段每格的能量會跳動 → 用隨時間變寬的窗平滑（約 ±3% 的時間）"""
    cs = np.concatenate([np.zeros((e.shape[0], 1)), np.cumsum(e, 1)], 1)
    i = np.arange(e.shape[1])
    h = np.maximum(1, (0.03 * i).astype(int))
    lo, hi = np.maximum(i - h, 0), np.minimum(i + h + 1, e.shape[1])
    return (cs[:, hi] - cs[:, lo]) / (hi - lo)


def decay_time(row, lo, hi):
    """Schroeder 反向積分 → lo 到 hi dB 之間的斜率 → 衰減 60 dB 的時間（秒）；row＝每 1 ms 的能量"""
    edc = np.cumsum(row[::-1])[::-1]
    db = 10 * np.log10(np.maximum(edc / max(edc[0], 1e-300), 1e-30))
    m = (db <= lo) & (db >= hi)
    t = np.arange(len(row)) * DT
    return float(-60 / np.polyfit(t[m], db[m], 1)[0]) if m.sum() > 3 else float("nan")


def frame(scene):
    """聽者的方向：面向兩個聲源的中間（水平），左邊＝上 × 前"""
    R = np.array(scene["rcv"])
    fwd = np.mean(scene["src"], 0) - R
    fwd[2] = 0
    fwd /= np.linalg.norm(fwd)
    left = np.cross([0, 0, 1.0], fwd)
    eL = math.cos(EAR) * fwd + math.sin(EAR) * left
    eR = math.cos(EAR) * fwd - math.sin(EAR) * left
    return fwd, left, eL, eR


def ang(u, e):
    return int(round(math.degrees(math.acos(float(np.clip(np.dot(u, e), -1, 1))))))


def volume(G, scene):
    """體積：用聲線量出平均自由路徑 l，V＝l·S/4（Kuttruff；形狀不規則也適用）"""
    S_area = sum(0.5 * np.linalg.norm(sum(np.cross(v[k] - v[0], v[k + 1] - v[0]) for k in range(1, len(v) - 1)))
                 for v, _m in scene["polys"])
    g = torch.Generator(device=DEV).manual_seed(5)
    o = torch.tensor(scene["rcv"], device=DEV, dtype=torch.float32).repeat(1 << 16, 1)
    d = torch.randn(1 << 16, 3, generator=g, device=DEV)
    d /= d.norm(dim=1, keepdim=True)
    tot, cnt = 0.0, 0
    for it in range(40):
        tm, ti = G.hit(o, d)
        good = ~torch.isinf(tm)
        if it:
            tot += float(tm[good].sum())
            cnt += int(good.sum())
        o = o + d * torch.where(good, tm, torch.zeros_like(tm))[:, None]
        nrm = G.tn[ti]
        nrm = torch.where(((nrm * d).sum(1) > 0)[:, None], -nrm, nrm)
        d = lambert(nrm, g)
        o = o + nrm * 1e-4
    return tot / cnt * S_area / 4


def render(name):
    t0 = time.time()
    scene = SCENES[name]()
    G = Geometry(scene)
    V = scene["V"] = volume(G, scene)
    T = target_rt(*scene["rt"])
    dirs = fib_dirs(N_DIR)
    hr, t_pre = hrir_table()
    _fwd, left, eL, eR = frame(scene)
    n_len = int(FS * (scene["rt"][0] * max(scene["rt"][1], 1) * 1.1 + 0.03))
    t_end = T.max() * 1.25 + 0.2
    dtab = directivity(scene["src_a"])
    base = np.array([MAT[m][0] for m in MAT_NAMES])
    # 1) 校正吸音：跟最後一樣的組合（鏡像法＋聲線追蹤）→ 量殘響時間 → 依比例調整（空氣吸收不調；到不了的頻段停在下限）
    k_b = np.ones(NB)
    src0 = scene["src"][0]
    d00 = float(np.linalg.norm(np.subtract(src0, scene["rcv"])))
    for it in range(10):
        alpha = np.clip(base * k_b, 0.002, 0.99)
        hf, _hd, _dc, _lk = trace(G, scene, alpha, src0, CAL_RAYS, t_end, scene["order"], False, 100 + it, dirs, dtab)
        e = energy_curve(ism(G, scene, alpha, src0, scene["order"], dtab), smooth(hf), d00)
        meas = np.array([decay_time(row[1:], -5, -35) for row in e])
        ratio = np.where(np.isfinite(meas), meas / T, 1)
        if np.all(np.abs(ratio - 1) < 0.03):
            break
        k_b = np.clip(k_b * np.clip(ratio, 1 / 3, 3), 0.02, 200)
    alpha = np.clip(base * k_b, 0.002, 0.99)
    nfft = 1 << (n_len + FS // 10 - 1).bit_length()
    f = np.fft.rfftfreq(nfft, 1 / FS)
    W = torch.tensor(band_weights(f), device=DEV, dtype=torch.float32)
    lim = torch.tensor(np.clip((21000 - f) / 3000, 0, 1) ** 2 * np.clip((f - 10) / 20, 0, 1) ** 2, device=DEV)
    ft = torch.tensor(f, device=DEV, dtype=torch.float64)
    Hf = torch.fft.rfft(torch.tensor(hr, device=DEV, dtype=torch.float32), n=nfft)
    Hf = Hf * torch.exp(2j * math.pi * torch.remainder(ft * t_pre, 1.0)).to(torch.complex64)[None]   # (181, 頻率)
    thL = np.array([ang(u, eL) for u in dirs])
    thR = np.array([ang(u, eR) for u in dirs])
    ir = np.zeros((n_len, 4))
    rep = {"volume_m3": round(V), "alpha_scale": k_b.round(3).tolist(), "sources": []}
    for si, src in enumerate(scene["src"]):
        hf, hd, direct, leaks = trace(G, scene, alpha, src, RAYS, t_end, scene["order"], False, 1 + si, dirs, dtab)
        d0 = float(np.linalg.norm(np.subtract(src, scene["rcv"])))
        Es = smooth(hf)
        paths = ism(G, scene, alpha, src, scene["order"], dtab)
        Y = torch.zeros(2, len(f), device=DEV, dtype=torch.complex64)
        # 2) 早期反射：每條路徑在頻率域放進去（精確的小數延遲），經過頭部模型
        for c0 in range(0, len(paths), 64):
            part = paths[c0:c0 + 64]
            A = torch.tensor(np.array([p[2] for p in part]), device=DEV, dtype=torch.float32) @ W   # (路徑, 頻率)
            tt = torch.tensor([p[0] for p in part], device=DEV, dtype=torch.float64)
            ph = torch.exp(-2j * math.pi * torch.remainder(ft[None] * tt[:, None], 1.0)).to(torch.complex64)
            for ear, e_ in ((0, eL), (1, eR)):
                idx = torch.tensor([ang(p[1], e_) for p in part], device=DEV)
                Y[ear] += (A * ph * Hf[idx]).sum(0)
        # 3) 後段：依回聲密度產生隨機正負脈衝，方向照聲線追蹤的方向分佈
        g = torch.Generator(device=DEV).manual_seed(77 + si)
        hds = hd.copy()
        hds[:, 1:-1] = (hd[:, :-2] + hd[:, 1:-1] + hd[:, 2:]) / 3
        tot_d = hds.sum(2, keepdims=True)
        Pb = np.where(tot_d > 0, hds / np.maximum(tot_d, 1e-300), 1 / N_DIR)
        P = Pb.mean(0)
        cdf = torch.tensor(np.cumsum(P, 1), device=DEV)
        cdf = cdf / cdf[:, -1:]
        tau = torch.arange(n_len, device=DEV, dtype=torch.float64) / FS
        tabs = tau + d0 / C
        mu = (4 * math.pi * C ** 3 * tabs ** 2 / V).clamp(2e4, FS / 2)
        isd = torch.rand(n_len, generator=g, device=DEV, dtype=torch.float64) < mu / FS
        ii = isd.nonzero().squeeze(1)
        j = (tabs[ii] / DT).long().clamp(max=Es.shape[1] - 1)
        jc = (tabs[ii] / DT_DIR).long().clamp(max=P.shape[0] - 1)
        Es_t = torch.tensor(Es, device=DEV)
        amp = torch.sqrt(Es_t[:, j].clamp(min=0) / (mu[ii] * DT))                         # (頻段, 脈衝)
        u = torch.rand(len(ii), 1, generator=g, device=DEV, dtype=torch.float64)
        dsel = torch.searchsorted(cdf[jc].contiguous(), u).squeeze(1).clamp(max=N_DIR - 1)
        Pb_t, P_t = torch.tensor(Pb, device=DEV), torch.tensor(P, device=DEV)
        wgt = Pb_t[:, jc, dsel] / P_t[jc, dsel].clamp(min=1e-12)
        sign = torch.where(torch.rand(len(ii), generator=g, device=DEV) < 0.5, -1.0, 1.0).double()
        amp = (amp * torch.sqrt(wgt) * sign).float()
        for c0 in range(0, N_DIR, 8):
            m = (dsel >= c0) & (dsel < c0 + 8)
            if not bool(m.any()):
                continue
            nm = int(m.sum())
            tr = torch.zeros(8, NB, nfft, device=DEV)
            dd = (dsel[m] - c0)[None].expand(NB, -1).reshape(-1)
            bb = torch.arange(NB, device=DEV)[:, None].expand(-1, nm).reshape(-1)
            tt = ii[m][None].expand(NB, -1).reshape(-1)
            tr.index_put_((dd, bb, tt), amp[:, m].reshape(-1), accumulate=True)
            sp = (torch.fft.rfft(tr, dim=2) * W[None]).sum(1)                           # (8, 頻率)
            Y[0] += (sp * Hf[torch.tensor(thL[c0:c0 + 8], device=DEV)]).sum(0)
            Y[1] += (sp * Hf[torch.tensor(thR[c0:c0 + 8], device=DEV)]).sum(0)
            del tr, sp
        Y *= lim[None].to(torch.complex64)
        rev = torch.fft.irfft(Y, n=nfft)[:, :n_len].double().cpu().numpy()
        fade = int(0.05 * FS)
        rev[:, -fade:] *= np.cos(np.linspace(0, np.pi / 2, fade)) ** 2
        # 4) 檢查（物理上的房間，還沒依直達/殘響比縮放）
        met = metrics(paths, Es, hd, d0, rev, scene, left, dirs, Hf, nfft, eL, eR, src)
        met.update(direct_check=round(direct, 2), leaks=leaks, paths=len(paths),
                   paths_by_order=[sum(1 for p in paths if p[3] == k) for k in range(1, scene["order"] + 1)],
                   first_ms=round(min(p[0] for p in paths) * 1000, 1) if paths else None)
        rep["sources"].append(met)
        rev /= math.sqrt((rev ** 2).sum())  # 兩耳總能量＝1（調音台再依直達/殘響比縮放）
        ir[:, si] = rev[si]                 # 左聲源：0＝左耳（L→L）、2＝右耳（L→R）；右聲源：1＝右耳、3＝左耳
        ir[:, 2 + si] = rev[1 - si]
        torch.cuda.empty_cache()
    rep.update(target=T.round(2).tolist(), seconds=round(time.time() - t0, 1), length_s=round(n_len / FS, 2),
               rays_per_source=RAYS)
    path = os.path.join(OUT, f"{name}.npy")
    with open(path + ".tmp", "wb") as fh:
        m = len(ir) * SAVE_FS // FS  # FFT 降取樣（20 kHz 以上本來就濾掉了），能量維持每個聲源＝1
        np.save(fh, (np.fft.irfft(np.fft.rfft(ir, axis=0)[:m // 2 + 1], m, axis=0) * math.sqrt(m / len(ir))).astype("<f4"))
    os.replace(path + ".tmp", path)  # 寫完才換：調音台不會讀到寫一半的檔
    return rep


def energy_curve(paths, Es, d0):
    """全指向麥克風的能量（各頻段每 1 ms，從直達聲開始）：直達聲＋鏡像法的反射＋聲線追蹤的其餘部分"""
    k0 = int(round(d0 / C / DT))
    n = Es.shape[1]
    e = np.zeros((NB, n))
    e[:, 0] += 1.0
    for t, _u, a, _k in paths:
        if int(t / DT) < n:
            e[:, int(t / DT)] += a ** 2
    e[:, :n - k0] += Es[:, k0:]
    return e


def metrics(paths, Es, hd, d0, rev, scene, left, dirs, Hf, nfft, eL, eR, src):
    """ISO 3382-1 指標（中頻＝500 Hz、1 kHz；C80、D50＝500–2k；LF＝125–1k），能量都以全指向麥克風計"""
    e = energy_curve(paths, Es, d0)
    mid, c3, lfb = [3, 4], [3, 4, 5], [1, 2, 3, 4]
    out = {"T30": [round(decay_time(e[b, 1:], -5, -35), 2) for b in range(NB)],
           "EDT_mid": round(float(np.mean([decay_time(e[b], 0, -10) for b in mid])), 2),
           "C80_dB": round(float(np.mean([10 * np.log10(e[b, :80].sum() / e[b, 80:].sum()) for b in c3])), 1),
           "D50": round(float(np.mean([e[b, :50].sum() / e[b].sum() for b in c3])), 2)}
    lat = np.zeros(NB)
    for t, u, a, _k in paths:
        if 0.005 <= t < 0.08:
            lat += a ** 2 * float(np.dot(u, left)) ** 2
    cos2 = (dirs @ left) ** 2
    for jc in range(hd.shape[1]):
        tc = (jc + 0.5) * DT_DIR - d0 / C
        if 0.005 <= tc < 0.08:
            lat += hd[:, jc] @ cos2
    out["LF"] = round(float(np.mean([lat[b] / e[b, :80].sum() for b in lfb])), 2)
    # 兩耳相關 IACC_E（0–80 ms，含直達聲，500/1k/2k 平均）
    u = np.subtract(src, scene["rcv"])
    u = u / np.linalg.norm(u)
    n80 = int(0.08 * FS)
    Hd = Hf[[ang(u, eL), ang(u, eR)]].cpu().numpy()
    x = np.fft.irfft(Hd, nfft)[:, :n80] + rev[:, :n80]
    W = band_weights(np.fft.rfftfreq(2 * n80, 1 / FS))
    X = np.fft.rfft(x, 2 * n80, axis=1)
    iacc = []
    lagmax = int(0.001 * FS)
    for b in c3:
        y = np.fft.irfft(X * W[b], 2 * n80, axis=1)
        cc = np.fft.irfft(np.fft.rfft(y[0], 4 * n80) * np.conj(np.fft.rfft(y[1], 4 * n80)), 4 * n80)
        cc = np.concatenate([cc[-lagmax:], cc[:lagmax + 1]])
        iacc.append(np.abs(cc).max() / math.sqrt((y[0] ** 2).sum() * (y[1] ** 2).sum()))
    out["IACC_E"] = round(float(np.mean(iacc)), 2)
    early = [10 * np.log10(np.mean(a[4:8] ** 2)) for t, _u, a, _k in paths if t <= 0.015]
    out["max_reflection_15ms_dB"] = round(max(early), 1) if early else None   # BS.1116：要 ≤ −10 dB（1–8 kHz）
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SCENES)
    path = os.path.join(OUT, "結果.json")
    report = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    report.update(device=torch.cuda.get_device_name(0) if DEV == "cuda" else "CPU", version=5)
    for name in names:
        report[name] = render(name)
        print(name, json.dumps(report[name], ensure_ascii=False), flush=True)
        if not QUICK:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
