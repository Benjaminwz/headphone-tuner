"""專案檢查（CI 同款，跨平台）：python tools/check.py

1. 電腦版 .pyw 能編譯（不執行，所以 Linux 也能跑）
2. 資料檔都是合法 JSON，且有必要的欄位
3. 網頁版 docs/data.json 與手機版 android/assets/data.json 一致
4. 網頁版 manifest 與 index.html 存在、圖示檔齊全
"""
import json
import os
import py_compile
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
errors = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        errors.append(msg)


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


# 1. 編譯
try:
    py_compile.compile(os.path.join(ROOT, "耳機調音台.pyw"),
                       cfile=os.path.join(tempfile.mkdtemp(), "x.pyc"), doraise=True)
    check(True, "耳機調音台.pyw 可編譯")
except py_compile.PyCompileError as exc:
    check(False, f"耳機調音台.pyw 編譯失敗：{exc}")
for rel in ("android/gen_data.py", "installer/build.py", "installer/make_icon.py"):
    try:
        py_compile.compile(os.path.join(ROOT, rel), cfile=os.path.join(tempfile.mkdtemp(), "x.pyc"), doraise=True)
        check(True, f"{rel} 可編譯")
    except py_compile.PyCompileError as exc:
        check(False, f"{rel} 編譯失敗：{exc}")

# 2. 資料檔
required = {"bands", "groups", "help", "estimated", "source_order"}
for rel in ("docs/data.json", "android/assets/data.json"):
    try:
        data = load(rel)
        missing = required - set(data)
        check(not missing, f"{rel} 欄位完整" + (f"（缺 {sorted(missing)}）" if missing else ""))
        styles = sum(len(g["styles"]) for g in data.get("groups", []))
        check(styles >= 50, f"{rel} 風格數量 {styles} >= 50")
    except (OSError, ValueError, KeyError) as exc:
        check(False, f"{rel} 讀取失敗：{exc}")

# 3. 一致
try:
    check(load("docs/data.json") == load("android/assets/data.json"),
          "docs/data.json 與 android/assets/data.json 一致（不一致請重跑 android/gen_data.py 並同步）")
except (OSError, ValueError) as exc:
    check(False, f"比對失敗：{exc}")

# 4. 網頁版
for rel in ("docs/index.html", "docs/manifest.webmanifest", "docs/icon-180.png",
            "docs/icon-192.png", "docs/icon-512.png"):
    check(os.path.isfile(os.path.join(ROOT, rel)), f"{rel} 存在")
try:
    load("docs/manifest.webmanifest")
    check(True, "docs/manifest.webmanifest 是合法 JSON")
except (OSError, ValueError) as exc:
    check(False, f"manifest 無法解析：{exc}")

print()
if errors:
    print(f"{len(errors)} 項失敗")
    sys.exit(1)
print("全部通過")
