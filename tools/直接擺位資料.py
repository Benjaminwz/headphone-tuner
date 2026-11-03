"""直接擺位（虛擬喇叭＋分離度）用的頭部資料 → 殘響/v4.npz（假人頭）、殘響/頭部/<代號>/v4.npz（真人）

python tools/直接擺位資料.py <資料夾>

資料夾＝放完整頭部量測和模擬檔的「殘響」資料夾：tools/殘響模擬.py --hrtf/--heads 做的 頭部/<代號>.npz，
tools/殘響模擬.py studio --dir 做的 studio_spk_dir.npy、頭部/<代號>/studio_spk_dir.npy（完整頭部量測太大，沒有放進專案）。
每個頭：仰角 0°、−45°～+45°（左＝正）每 1° 的頭部量測——最近三個量測點內插（大小取對數平均、兩耳延遲線性平均；
延遲＝300–1500 Hz 超額相位的斜率，相對正前方到頭中心，Kulkarni 等 1999 證明最小相位＋延遲聽起來跟原本一樣），
大小存成 20 Hz–24 kHz 每 1/48 八度（dB，float16：1/3 八度平滑後跟原本差不到 0.1 dB），加上兩耳延遲；
錄音室虛擬喇叭裡的直達聲存前 2048 點（96 kHz，後面都是 0）。調音台讀進來再做成最小相位（v4_table）"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "殘響")
AZ0, NAZ, PER_OCT = -45.0, 91, 48
GRID = 20 * 2 ** (np.arange(int(PER_OCT * np.log2(24000 / 20)) + 1) / PER_OCT)


def minphase_nd(mag):
    """大小 → 最小相位的頻率響應（倒頻譜法，最後一軸是頻率）"""
    n = 2 * (mag.shape[-1] - 1)
    c = np.fft.irfft(np.log(np.maximum(mag, 1e-8)), n, axis=-1)
    c[..., 1:n // 2] *= 2
    c[..., n // 2 + 1:] = 0
    return np.exp(np.fft.rfft(c, n, axis=-1))


def table(path):
    """完整頭部量測 → (每 1/48 八度的大小 dB (91, 2, len(GRID))、兩耳延遲 (91, 2) 秒)"""
    d = np.load(path)
    U, h, t0 = d["dirs"].astype(float), d["hrir"], float(d["t0"])
    nf = 8192
    f = np.fft.rfftfreq(nf, 1 / 96000)
    az = np.radians(AZ0 + np.arange(NAZ))
    V = np.stack([np.cos(az), np.sin(az), np.zeros(NAZ)], 1)
    ang = np.degrees(np.arccos(np.clip(V @ U.T, -1, 1)))
    idx = np.argsort(ang, 1)[:, :3]
    w = 1 / (np.take_along_axis(ang, idx, 1) + 0.5) ** 2
    w /= w.sum(1, keepdims=True)
    sel = np.unique(idx)
    H = np.fft.rfft(h[sel].astype(float), nf, axis=2)
    mag = np.abs(H)
    ex = np.unwrap(np.angle(H / minphase_nd(mag)), axis=2)
    b = (f >= 300) & (f <= 1500)
    tau = -np.polyfit(2 * np.pi * f[b], ex[..., b].reshape(-1, int(b.sum())).T, 1)[0].reshape(len(sel), 2) - t0
    rows = np.searchsorted(sel, idx)
    db = 20 / np.log(10) * (w[..., None, None] * np.log(np.maximum(mag[rows], 1e-8))).sum(1)
    lo, hi = GRID * 2 ** (-0.5 / PER_OCT), GRID * 2 ** (0.5 / PER_OCT)  # 每格：前後半格的能量平均
    cs = np.concatenate([np.zeros(db.shape[:-1] + (1,)), np.cumsum(10 ** (db / 10), -1)], -1)
    i0, i1 = np.searchsorted(f, lo), np.searchsorted(f, hi)
    avg = 10 * np.log10((cs[..., i1] - cs[..., i0]) / np.maximum(i1 - i0, 1) + 1e-30)
    interp = np.stack([[np.interp(GRID, f, db[a, e]) for e in (0, 1)] for a in range(NAZ)])  # 低頻：比原始格還細就內插
    return np.where(i1 - i0 < 2, interp, avg), (w[..., None] * tau[rows]).sum(1)


def main():
    src = sys.argv[1]
    heads = ["KU100"] + sorted((h for h in os.listdir(os.path.join(OUT, "頭部")) if os.path.isdir(os.path.join(OUT, "頭部", h))),
                               key=lambda h: int(h[1:]))
    for hid in heads:
        db, tau = table(os.path.join(src, "頭部", f"{hid}.npz"))
        sub = [] if hid == "KU100" else ["頭部", hid]
        direct = np.load(os.path.join(src, *sub, "studio_spk_dir.npy"))
        out = os.path.join(OUT, *sub, "v4.npz")
        np.savez_compressed(out, f=GRID.astype(np.float32), db=db.astype(np.float16), tau=tau.astype(np.float32),
                            dir=direct[:2048].astype(np.float32), az0=np.float32(AZ0), step=np.float32(1.0))
        print(hid, out, os.path.getsize(out) // 1024, "KB", "直達聲 2048 點以後最大 %.1e" % np.abs(direct[2048:]).max())


if __name__ == "__main__":
    main()
