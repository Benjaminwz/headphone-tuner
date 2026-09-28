"""從電腦版（耳機調音台.pyw）匯出手機版要用的資料：風格、白話介紹、細調頻段、名詞說明、推估型號 → assets/data.json，
另外畫出 App 圖示（向量圖）。電腦版改了風格之後重跑這支就好，手機版跟著更新。
用法：python android/gen_data.py"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("pc", os.path.join(ROOT, "耳機調音台.pyw"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

data = {
    "bands": [{"name": n, "type": k, "fc": f, "q": q, "hint": h} for n, k, f, q, h in pc.BANDS],
    "groups": [{"name": g, "styles": [{"name": n, "vals": [float(v) for v in vals], "width": w, "cf": cf,
                                       "room": pc.STYLE_ROOM.get(n, 0), "plain": pc.PLAIN.get(n, "")}
                                      for n, vals, w, cf, _src in styles]} for g, styles in pc.STYLE_GROUPS],
    "help": {k: v for k, v in pc.HELP.items() if k in ("低頻", "厚度", "人聲", "臨場感", "高頻", "音量優先", "開啟 EQ")},
    "estimated": pc.ESTIMATED,
    "source_order": pc.SOURCE_ORDER,
}
os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
with open(os.path.join(HERE, "assets", "data.json"), "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

# ---------- App 圖示：跟電腦版同一個設計（256 格座標）縮進 108×108 的自適應圖示安全區 ----------
S, CX, CY = 0.33, 128, 134
X = lambda x: 54 + (x - CX) * S
Y = lambda y: 54 + (y - CY) * S


def rrect(x0, y0, x1, y1, r):
    x0, y0, x1, y1, r = X(x0), Y(y0), X(x1), Y(y1), r * S
    w, h = x1 - x0 - 2 * r, y1 - y0 - 2 * r
    return (f"M{x0 + r:.2f},{y0:.2f} h{w:.2f} a{r:.2f},{r:.2f} 0 0 1 {r:.2f},{r:.2f} v{h:.2f} "
            f"a{r:.2f},{r:.2f} 0 0 1 {-r:.2f},{r:.2f} h{-w:.2f} a{r:.2f},{r:.2f} 0 0 1 {-r:.2f},{-r:.2f} "
            f"v{-h:.2f} a{r:.2f},{r:.2f} 0 0 1 {r:.2f},{-r:.2f} z")


shapes = " ".join(rrect(*a) for a in ((34, 128, 76, 206, 16), (180, 128, 222, 206, 16),
                                      (99, 150, 115, 200, 7), (120, 118, 136, 200, 7), (141, 164, 157, 200, 7)))
band = f"M{X(48):.2f},{Y(142):.2f} A{80 * S:.2f},{80 * S:.2f} 0 0 1 {X(208):.2f},{Y(142):.2f}"
vec = f'''<?xml version="1.0" encoding="utf-8"?>
<!-- 由 gen_data.py 產生：白色耳機＋三條等化器（背景色在 values/colors.xml） -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFF" android:pathData="{shapes}" />
    <path android:strokeColor="#FFFFFF" android:strokeWidth="{20 * S:.2f}" android:fillColor="#00000000"
        android:pathData="{band}" />
</vector>
'''
os.makedirs(os.path.join(HERE, "res", "drawable"), exist_ok=True)
with open(os.path.join(HERE, "res", "drawable", "ic_fg.xml"), "w", encoding="utf-8") as fh:
    fh.write(vec)
print("styles", sum(len(g["styles"]) for g in data["groups"]), "groups", len(data["groups"]))
