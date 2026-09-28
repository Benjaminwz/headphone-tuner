package io.github.benjaminwz.headphonetuner;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/** 耳機調音台（手機版）：跟電腦版同一套風格、耳機校正與暖色介面 */
public class MainActivity extends Activity {
    static final int BG = 0xFFFBF5EE, CARD = 0xFFFFFFFF, TEXT = 0xFF3B2A1E, SUB = 0xFF8C7461, ACCENT = 0xFFD9692B,
            PILL = 0xFFF8EEE3, LINE = 0xFFEFE2D3, FILL = 0xFFFCE8D8, TWEAK = 0xFF8A5A36, GREEN = 0xFF4E8A3E,
            WARN = 0xFFB8452B, VALUE = 0xFFC0561B;

    private JSONObject st;
    private float dp;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Map<String, Double> headroomCache = new HashMap<>();
    private TextView statusTv, hpBtn, infoName, infoPlain;
    private Switch enabledSw, loudSw;
    private LinearLayout baseBox, tabBox, styleGrid, presetBox, modeBox;
    private CurveView curve;
    private final SeekBar[] bars = new SeekBar[5];
    private final TextView[] barVals = new TextView[5];
    private EditText search;
    private int group = 0;
    private boolean holding = false;

    private final Runnable push = this::pushToService;
    private final Runnable statusTick = new Runnable() {
        @Override
        public void run() {
            paintStatus();
            ui.postDelayed(this, 1500);
        }
    };

    // ---------------------------------------------------------------- 生命週期
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        dp = getResources().getDisplayMetrics().density;
        getWindow().setStatusBarColor(BG);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        try {
            Eq.load(this);
        } catch (Exception e) {
            TextView t = tv("資料讀取失敗：" + e, 15, WARN, false);
            setContentView(t);
            return;
        }
        loadState();
        setContentView(buildUi());
        refreshAll();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        if (st.optJSONObject("hp") == null) ui.postDelayed(this::pickHeadphone, 400);
    }

    @Override
    protected void onResume() {
        super.onResume();
        ui.post(statusTick);
    }

    @Override
    protected void onPause() {
        super.onPause();
        ui.removeCallbacks(statusTick);
    }

    // ---------------------------------------------------------------- 狀態
    private SharedPreferences prefs() {
        return getSharedPreferences(EqService.PREFS, MODE_PRIVATE);
    }

    private void loadState() {
        try {
            st = new JSONObject(prefs().getString("state", "{}"));
        } catch (Exception e) {
            st = new JSONObject();
        }
        try {
            if (!st.has("enabled")) st.put("enabled", true);
            if (!st.has("loud")) st.put("loud", true);  // 手機、藍牙常常不夠大聲：預設音量優先
            if (!st.has("mode")) st.put("mode", "global");
            if (!st.has("bands")) st.put("bands", new JSONArray(new double[]{0, 0, 0, 0, 0}));
            if (!st.has("presets")) st.put("presets", new JSONObject());
            if (!st.has("base")) st.put("base", Eq.defaultBase(st.optJSONObject("hp")));
        } catch (Exception ignored) {
        }
    }

    private void save() {
        prefs().edit().putString("state", st.toString()).apply();
    }

    private double[] vals() {
        JSONArray a = st.optJSONArray("bands");
        double[] v = new double[5];
        for (int i = 0; i < 5; i++) v[i] = a == null ? 0 : a.optDouble(i, 0);
        return v;
    }

    private void setVals(double[] v, String styleName) {
        try {
            JSONArray a = new JSONArray();
            for (double x : v) a.put(x);
            st.put("bands", a);
            if (styleName == null) st.remove("style");
            else st.put("style", styleName);
        } catch (Exception ignored) {
        }
    }

    private List<Eq.Filter> baseFilters() {
        String key = st.optString("base", "none");
        for (Eq.Base b : Eq.bases(st.optJSONObject("hp"))) if (b.key.equals(key)) return b.filters;
        return new ArrayList<>();
    }

    /** 固定預留＝這支耳機這種校正 × 所有風格裡最大的加強（跟電腦版一樣，切換風格音量不變） */
    private double headroomFor(List<Eq.Filter> base) {
        JSONObject hp = st.optJSONObject("hp");
        String key = (hp == null ? "" : hp.optString("name")) + "|" + st.optString("base");
        Double c = headroomCache.get(key);
        if (c != null) return c;
        double[] bc = Eq.curve(base), worst = {0};
        Map<String, double[]> done = new HashMap<>();
        for (Eq.Style s : Eq.STYLES) {
            String k = java.util.Arrays.toString(s.vals);
            if (done.containsKey(k)) continue;
            double[] sc = Eq.curve(Eq.styleFilters(s.vals));
            done.put(k, sc);
            for (int i = 0; i < bc.length; i++) worst[0] = Math.max(worst[0], bc[i] + sc[i]);
        }
        double hr = Math.min(18, Math.ceil(worst[0] * 2) / 2);
        headroomCache.put(key, hr);
        return hr;
    }

    // ---------------------------------------------------------------- 套用
    private void refreshAll() {
        paintBases();
        paintTabs();
        showGroup(group);
        paintBars();
        paintPresets();
        paintModes();
        apply();
    }

    private void apply() {
        List<Eq.Filter> base = baseFilters(), style = Eq.styleFilters(vals());
        double[] bc = Eq.curve(base), sc = Eq.curve(style), total = new double[bc.length];
        for (int i = 0; i < bc.length; i++) total[i] = bc[i] + sc[i];
        boolean on = st.optBoolean("enabled", true);
        curve.set(total, sc, on && !holding);
        highlightStyle();
        JSONObject hp = st.optJSONObject("hp");
        hpBtn.setText("耳機：" + (hp == null ? "還沒選（點我選）" : hp.optString("name")) + "　▸");
        save();
        ui.removeCallbacks(push);
        ui.postDelayed(push, 120);  // 拖滑桿時不要每一格都通知背景服務
    }

    /** 算出 64 段的增益和預留音量，交給背景服務 */
    private void pushToService() {
        boolean on = st.optBoolean("enabled", true);
        if (!on) {
            EqService.stop(this);
            paintStatus();
            return;
        }
        List<Eq.Filter> base = baseFilters(), style = Eq.styleFilters(vals());
        List<Eq.Filter> both = new ArrayList<>(base);
        both.addAll(style);
        double peak = Eq.max(Eq.curve(both));
        double need = Math.max(0, Math.ceil(peak * 2) / 2);
        double hr = st.optBoolean("loud", true) ? need : Math.max(need, headroomFor(base));
        try {
            JSONArray g = new JSONArray();
            for (double f : EqService.centers()) g.put(holding ? 0 : Eq.at(base, f) + Eq.at(style, f));
            JSONObject a = new JSONObject().put("on", true).put("preamp", -hr).put("gains", g)
                    .put("mode", st.optString("mode", "global"));
            prefs().edit().putString("applied", a.toString()).apply();
        } catch (Exception ignored) {
        }
        EqService.start(this);
        ui.postDelayed(this::paintStatus, 400);
    }

    private void paintStatus() {
        boolean on = st.optBoolean("enabled", true);
        if (!on) {
            statusTv.setText("● 已關閉：完全不處理（原音）");
            statusTv.setTextColor(SUB);
        } else {
            statusTv.setText("● " + (EqService.running ? EqService.status : "啟動中…"));
            statusTv.setTextColor(EqService.status.startsWith("這支") ? WARN : GREEN);
        }
    }

    // ---------------------------------------------------------------- 畫面
    private View buildUi() {
        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(BG);
        sv.setFillViewport(true);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(px(16), px(20), px(16), px(28));
        sv.addView(root);

        root.addView(tv("耳機調音台", 26, TEXT, true));
        statusTv = tv("", 13, GREEN, false);
        statusTv.setPadding(0, px(2), 0, px(12));
        root.addView(statusTv);

        // 開關
        LinearLayout c = card(root, null);
        enabledSw = switchRow(c, "開啟 EQ", "關掉＝完全不處理（原音）", st.optBoolean("enabled", true), v -> {
            put("enabled", v);
            apply();
        });
        loudSw = switchRow(c, "音量優先", "比較大聲，換風格音量會變（藍牙、手機建議打開）", st.optBoolean("loud", true), v -> {
            put("loud", v);
            apply();
        });
        TextView hold = chip("按住聽原音", false);
        hold.setGravity(Gravity.CENTER);
        hold.setPadding(px(12), px(12), px(12), px(12));
        hold.setOnTouchListener((v, e) -> {
            if (e.getAction() == MotionEvent.ACTION_DOWN) setHolding(true, hold);
            else if (e.getAction() == MotionEvent.ACTION_UP || e.getAction() == MotionEvent.ACTION_CANCEL) setHolding(false, hold);
            return true;
        });
        c.addView(hold, lp(-1, -2, 0, px(10), 0, 0));
        c.addView(tv("按住時是原本的聲音（音量一樣），放開就回來，方便比較差別", 12, SUB, false), lp(-1, -2, 0, px(6), 0, 0));

        // 耳機
        c = card(root, "耳機校正");
        hpBtn = chip("", false);
        hpBtn.setOnClickListener(v -> pickHeadphone());
        c.addView(hpBtn, lp(-1, -2, 0, 0, 0, px(8)));
        baseBox = vbox();
        c.addView(baseBox);
        c.addView(tv("依專業量測把耳機調到最多人喜歡的平衡（Harman 目標），資料來自 AutoEQ", 12, SUB, false),
                lp(-1, -2, 0, px(6), 0, 0));

        // 快速風格
        c = card(root, "快速風格");
        search = new EditText(this);
        search.setHint("搜尋：搖滾、人聲、低音…");
        search.setTextSize(15);
        search.setTextColor(TEXT);
        search.setHintTextColor(SUB);
        search.setSingleLine(true);
        search.setBackground(round(PILL, 10, 0));
        search.setPadding(px(12), px(10), px(12), px(10));
        search.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int b, int d) {
            }

            public void onTextChanged(CharSequence s, int a, int b, int d) {
            }

            public void afterTextChanged(Editable e) {
                String q = e.toString().trim().toLowerCase();
                if (q.isEmpty()) showGroup(group);
                else {
                    List<Integer> hits = new ArrayList<>();
                    for (int i = 0; i < Eq.STYLES.size(); i++) {
                        Eq.Style s = Eq.STYLES.get(i);
                        if (s.name.toLowerCase().contains(q) || s.plain.toLowerCase().contains(q)) hits.add(i);
                    }
                    showList(hits, -1);
                }
            }
        });
        c.addView(search, lp(-1, -2, 0, 0, 0, px(8)));
        HorizontalScrollView hs = new HorizontalScrollView(this);
        hs.setHorizontalScrollBarEnabled(false);
        tabBox = new LinearLayout(this);
        hs.addView(tabBox);
        c.addView(hs, lp(-1, -2, 0, 0, 0, px(8)));
        styleGrid = vbox();
        c.addView(styleGrid);
        LinearLayout info = vbox();
        info.setBackground(round(PILL, 12, 0));
        info.setPadding(px(12), px(10), px(12), px(12));
        infoName = tv("", 16, VALUE, true);
        infoPlain = tv("", 14, TEXT, false);
        info.addView(infoName);
        info.addView(infoPlain);
        c.addView(info, lp(-1, -2, 0, px(10), 0, 0));

        // 曲線
        c = card(root, "EQ 曲線");
        c.addView(tv("橘線＝整體效果　咖啡色虛線＝你的細調", 12, SUB, false));
        curve = new CurveView(this);
        c.addView(curve, lp(-1, px(190), 0, px(6), 0, 0));

        // 細調
        c = card(root, "細調");
        for (int i = 0; i < 5; i++) {
            Eq.Band band = Eq.BANDS.get(i);
            LinearLayout row = new LinearLayout(this);
            row.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout lab = vbox();
            lab.addView(tv(band.name, 15, TEXT, true));
            lab.addView(tv(band.hint, 11, SUB, false));
            row.addView(lab, new LinearLayout.LayoutParams(px(96), -2));
            SeekBar sb = new SeekBar(this);
            sb.setMax(24);
            final int idx = i;
            sb.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                public void onProgressChanged(SeekBar s, int p, boolean user) {
                    if (!user) return;
                    double[] v = vals();
                    v[idx] = (p - 12) / 2.0;
                    setVals(v, null);
                    barVals[idx].setText(fmtDb(v[idx]));
                    apply();
                }

                public void onStartTrackingTouch(SeekBar s) {
                }

                public void onStopTrackingTouch(SeekBar s) {
                }
            });
            bars[i] = sb;
            row.addView(sb, new LinearLayout.LayoutParams(0, -2, 1));
            barVals[i] = tv("", 14, VALUE, true);
            barVals[i].setGravity(Gravity.END);
            row.addView(barVals[i], new LinearLayout.LayoutParams(px(64), -2));
            c.addView(row, lp(-1, -2, 0, px(4), 0, px(4)));
        }
        TextView reset = chip("細調歸零", false);
        reset.setOnClickListener(v -> {
            setVals(new double[5], null);
            paintBars();
            apply();
        });
        c.addView(reset, lp(-2, -2, 0, px(6), 0, 0));

        // 我的預設
        c = card(root, "我的預設");
        TextView saveBtn = chip("＋ 把目前的設定存起來", true);
        saveBtn.setOnClickListener(v -> savePreset());
        c.addView(saveBtn, lp(-2, -2, 0, 0, 0, px(8)));
        presetBox = vbox();
        c.addView(presetBox);
        c.addView(tv("點一下套用，按住可以刪除", 12, SUB, false), lp(-1, -2, 0, px(6), 0, 0));

        // 說明
        c = card(root, "套用方式與說明");
        modeBox = vbox();
        c.addView(modeBox);
        c.addView(tv("• 「整支手機」對所有 App 都有效；有些手機不允許，會自動改成「個別播放 App」。\n"
                + "• Tidal：不要打開「獨佔模式」「強制音量」這類讓外接解碼器直接輸出的選項，不然會繞過等化器。\n"
                + "• 接 USB 解碼器（例如 KA13）也能用；沒效果就切到「個別播放 App」試試（切換後，播放 App 要停止再重新播放一次才會接上）。\n"
                + "• 手機版只調音色（耳機校正＋風格＋細調）；聲場寬度、交叉饋送、殘響只有電腦版有。\n"
                + "• 通知列的常駐通知是 Android 規定的，關掉 EQ 就會消失。", 13, SUB, false), lp(-1, -2, 0, px(8), 0, 0));
        TextView gh = tv("電腦版和原始碼：github.com/Benjaminwz/headphone-tuner", 12, ACCENT, false);
        gh.setOnClickListener(v -> startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/Benjaminwz/headphone-tuner"))));
        c.addView(gh, lp(-1, -2, 0, px(10), 0, 0));
        return sv;
    }

    private void setHolding(boolean down, TextView btn) {
        if (holding == down || !st.optBoolean("enabled", true)) return;
        holding = down;
        btn.setBackground(round(down ? ACCENT : PILL, 10, 0));
        btn.setTextColor(down ? 0xFFFFFFFF : TEXT);
        apply();
        ui.removeCallbacks(push);
        pushToService();  // 按住要馬上生效
    }

    private void paintBases() {
        List<View> v = new ArrayList<>();
        String cur = st.optString("base");
        for (Eq.Base b : Eq.bases(st.optJSONObject("hp"))) {
            TextView ch = chip(b.label, b.key.equals(cur));
            ch.setOnClickListener(x -> {
                put("base", b.key);
                paintBases();
                apply();
            });
            v.add(ch);
        }
        wrap(baseBox, v, 2);
    }

    private void paintTabs() {
        tabBox.removeAllViews();
        for (int i = 0; i < Eq.GROUPS.size(); i++) {
            TextView t = chip(Eq.GROUPS.get(i), i == group);
            final int g = i;
            t.setOnClickListener(v -> {
                search.setText("");
                showGroup(g);
            });
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-2, -2);
            p.setMargins(0, 0, px(6), 0);
            tabBox.addView(t, p);
        }
    }

    private void showGroup(int g) {
        group = g;
        paintTabs();
        List<Integer> idx = new ArrayList<>();
        for (int i = 0; i < Eq.STYLES.size(); i++) if (Eq.STYLES.get(i).group.equals(Eq.GROUPS.get(g))) idx.add(i);
        showList(idx, g);
    }

    private void showList(List<Integer> idx, int g) {
        List<View> v = new ArrayList<>();
        int cur = currentStyle();
        for (int i : idx) {
            Eq.Style s = Eq.STYLES.get(i);
            TextView ch = chip(s.name, i == cur);
            ch.setGravity(Gravity.CENTER);
            ch.setOnClickListener(x -> applyStyle(i));
            v.add(ch);
        }
        if (v.isEmpty()) v.add(tv("找不到，換個字試試（例：搖滾、人聲、低音）", 13, SUB, false));
        wrap(styleGrid, v, 2);
        showInfo(cur);
    }

    private void applyStyle(int i) {
        Eq.Style s = Eq.STYLES.get(i);
        setVals(s.vals.clone(), s.name);
        paintBars();
        apply();
        if (search.getText().length() > 0) afterSearchRefresh();
        else showGroup(group);
    }

    private void afterSearchRefresh() {
        search.setText(search.getText());  // 重跑一次篩選，更新選中的顏色
    }

    private int currentStyle() {
        double[] v = vals();
        String name = st.optString("style", "");
        int first = -1;
        for (int i = 0; i < Eq.STYLES.size(); i++) {
            Eq.Style s = Eq.STYLES.get(i);
            boolean same = true;
            for (int k = 0; k < 5; k++) same &= Math.abs(s.vals[k] - v[k]) < 0.05;
            if (!same) continue;
            if (s.name.equals(name)) return i;
            if (first < 0 || (s.group.equals(Eq.GROUPS.get(group)) && !Eq.STYLES.get(first).group.equals(Eq.GROUPS.get(group))))
                first = i;
        }
        return first;
    }

    private void highlightStyle() {
        showInfo(currentStyle());
    }

    private void showInfo(int i) {
        if (infoName == null) return;
        if (i < 0) {
            infoName.setText("自訂調音");
            infoPlain.setText("跟內建風格都不一樣，喜歡可以存到「我的預設」");
            return;
        }
        Eq.Style s = Eq.STYLES.get(i);
        infoName.setText(s.name);
        infoPlain.setText(s.plain + (s.spatial() ? "\n（這個風格的聲場、交叉饋送或殘響只有電腦版有，手機套用音色部分）" : ""));
    }

    private void paintBars() {
        double[] v = vals();
        for (int i = 0; i < 5; i++) {
            bars[i].setProgress((int) Math.round(v[i] * 2 + 12));
            barVals[i].setText(fmtDb(v[i]));
        }
    }

    private void paintPresets() {
        List<View> v = new ArrayList<>();
        JSONObject ps = st.optJSONObject("presets");
        if (ps != null) {
            for (Iterator<String> it = ps.keys(); it.hasNext(); ) {
                String name = it.next();
                TextView ch = chip(name, false);
                ch.setOnClickListener(x -> {
                    JSONObject p = ps.optJSONObject(name);
                    if (p == null) return;
                    put("base", p.optString("base", st.optString("base")));
                    JSONArray a = p.optJSONArray("bands");
                    double[] vv = new double[5];
                    for (int k = 0; k < 5; k++) vv[k] = a == null ? 0 : a.optDouble(k, 0);
                    setVals(vv, null);
                    paintBases();
                    paintBars();
                    apply();
                    showGroup(group);
                    toast("已套用「" + name + "」");
                });
                ch.setOnLongClickListener(x -> {
                    new AlertDialog.Builder(this).setMessage("刪除「" + name + "」？")
                            .setPositiveButton("刪除", (d, w) -> {
                                ps.remove(name);
                                save();
                                paintPresets();
                            }).setNegativeButton("取消", null).show();
                    return true;
                });
                v.add(ch);
            }
        }
        if (v.isEmpty()) v.add(tv("還沒有存任何設定", 13, SUB, false));
        wrap(presetBox, v, 2);
    }

    private void paintModes() {
        List<View> v = new ArrayList<>();
        String cur = st.optString("mode", "global");
        String[][] modes = {{"global", "整支手機（建議）"}, {"session", "個別播放 App"}};
        for (String[] m : modes) {
            TextView ch = chip(m[1], m[0].equals(cur));
            ch.setGravity(Gravity.CENTER);
            ch.setOnClickListener(x -> {
                put("mode", m[0]);
                paintModes();
                EqService.stop(this);  // 換套用方式：重新啟動背景服務
                apply();
            });
            v.add(ch);
        }
        wrap(modeBox, v, 2);
    }

    // ---------------------------------------------------------------- 選耳機、存預設
    private void pickHeadphone() {
        LinearLayout box = vbox();
        box.setPadding(px(20), px(12), px(20), 0);
        TextView hint = tv("輸入耳機型號（例：HD 600、XM5、AirPods Max）。無線耳機有「ANC on／off」兩種量測的，選你平常用的模式。",
                13, SUB, false);
        box.addView(hint);
        EditText q = new EditText(this);
        q.setSingleLine(true);
        q.setInputType(InputType.TYPE_CLASS_TEXT);
        box.addView(q, lp(-1, -2, 0, px(8), 0, 0));
        TextView msg = tv("下載耳機清單中…", 12, SUB, false);
        box.addView(msg);
        ListView list = new ListView(this);
        ArrayAdapter<String> ad = new ArrayAdapter<>(this, android.R.layout.simple_list_item_1, new ArrayList<>());
        list.setAdapter(ad);
        box.addView(list, lp(-1, px(320), 0, px(6), 0, 0));
        AlertDialog dlg = new AlertDialog.Builder(this).setTitle("選擇耳機").setView(box)
                .setNeutralButton("找不到，先不校正", (d, w) -> {
                    try {
                        setHp(new JSONObject().put("name", "不校正").put("sources", new JSONArray()));
                    } catch (Exception ignored) {
                    }
                })
                .setNegativeButton("取消", null).create();
        final Map<String, List<String[]>>[] models = new Map[]{null};
        final List<String> shown = new ArrayList<>();
        Runnable filter = () -> {
            if (models[0] == null) return;
            String k = Eq.norm(q.getText().toString());
            shown.clear();
            if (!k.isEmpty()) for (String n : models[0].keySet()) if (Eq.norm(n).contains(k)) shown.add(n);
            java.util.Collections.sort(shown, (a, b2) -> a.length() != b2.length() ? a.length() - b2.length() : a.compareTo(b2));
            if (shown.size() > 200) shown.subList(200, shown.size()).clear();
            ad.clear();
            for (String n : shown) ad.add(n);
            msg.setText(k.isEmpty() ? "共 " + models[0].size() + " 款耳機，輸入型號搜尋" : "找到 " + shown.size() + " 個");
        };
        q.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int b, int c) {
            }

            public void onTextChanged(CharSequence s, int a, int b, int c) {
            }

            public void afterTextChanged(Editable e) {
                filter.run();
            }
        });
        list.setOnItemClickListener((p, v, pos, id) -> {
            String name = shown.get(pos);
            msg.setText("下載「" + name + "」的校正資料中…");
            new Thread(() -> {
                try {
                    JSONObject hp = Eq.downloadHeadphone(name, models[0].get(name));
                    ui.post(() -> {
                        setHp(hp);
                        dlg.dismiss();
                    });
                } catch (Exception e) {
                    ui.post(() -> msg.setText("下載失敗：" + e.getMessage()));
                }
            }).start();
        });
        dlg.show();
        new Thread(() -> {
            try {
                Map<String, List<String[]>> m = Eq.loadIndex(this);
                ui.post(() -> {
                    models[0] = m;
                    filter.run();
                });
            } catch (Exception e) {
                ui.post(() -> msg.setText("耳機清單下載失敗（要有網路）：" + e.getMessage()));
            }
        }).start();
    }

    private void setHp(JSONObject hp) {
        try {
            st.put("hp", hp);
            st.put("base", Eq.defaultBase(hp));
        } catch (Exception ignored) {
        }
        headroomCache.clear();
        paintBases();
        apply();
        toast("耳機：" + hp.optString("name"));
    }

    private void savePreset() {
        EditText name = new EditText(this);
        name.setSingleLine(true);
        int cur = currentStyle();
        name.setText(cur >= 0 ? Eq.STYLES.get(cur).name : "");
        new AlertDialog.Builder(this).setTitle("幫這組設定取個名字").setView(name)
                .setPositiveButton("儲存", (d, w) -> {
                    String n = name.getText().toString().trim();
                    if (n.isEmpty()) return;
                    try {
                        JSONArray a = new JSONArray();
                        for (double x : vals()) a.put(x);
                        st.getJSONObject("presets").put(n, new JSONObject().put("base", st.optString("base")).put("bands", a));
                    } catch (Exception ignored) {
                    }
                    save();
                    paintPresets();
                    toast("已儲存「" + n + "」");
                }).setNegativeButton("取消", null).show();
    }

    // ---------------------------------------------------------------- 小工具
    interface OnBool {
        void on(boolean v);
    }

    private void put(String k, Object v) {
        try {
            st.put(k, v);
        } catch (Exception ignored) {
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private static String fmtDb(double v) {
        return v == 0 ? "0 dB" : String.format(java.util.Locale.US, "%+.1f dB", v);
    }

    private int px(float v) {
        return Math.round(v * dp);
    }

    private GradientDrawable round(int color, float r, int stroke) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(r * dp);
        if (stroke != 0) g.setStroke(px(1), stroke);
        return g;
    }

    private TextView tv(String t, float sp, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(t);
        v.setTextSize(sp);
        v.setTextColor(color);
        if (bold) v.setTypeface(Typeface.DEFAULT_BOLD);
        v.setLineSpacing(0, 1.15f);
        return v;
    }

    private TextView chip(String t, boolean selected) {
        TextView v = tv(t, 14, selected ? 0xFFFFFFFF : TEXT, false);
        v.setBackground(round(selected ? ACCENT : PILL, 10, 0));
        v.setPadding(px(12), px(9), px(12), px(9));
        return v;
    }

    private LinearLayout vbox() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        return l;
    }

    private LinearLayout.LayoutParams lp(int w, int h, int l, int t, int r, int b) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h);
        p.setMargins(l, t, r, b);
        return p;
    }

    private LinearLayout card(LinearLayout parent, String title) {
        LinearLayout c = vbox();
        c.setBackground(round(CARD, 16, LINE));
        c.setPadding(px(16), px(14), px(16), px(16));
        if (title != null) {
            LinearLayout head = new LinearLayout(this);
            head.setGravity(Gravity.CENTER_VERTICAL);
            View bar = new View(this);
            bar.setBackgroundColor(ACCENT);
            head.addView(bar, new LinearLayout.LayoutParams(px(3), px(16)));
            TextView t = tv(title, 17, TEXT, true);
            t.setPadding(px(8), 0, 0, 0);
            head.addView(t);
            c.addView(head, lp(-1, -2, 0, 0, 0, px(10)));
        }
        parent.addView(c, lp(-1, -2, 0, 0, 0, px(12)));
        return c;
    }

    private Switch switchRow(LinearLayout parent, String title, String sub, boolean on, OnBool cb) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout lab = vbox();
        lab.addView(tv(title, 16, TEXT, true));
        lab.addView(tv(sub, 12, SUB, false));
        row.addView(lab, new LinearLayout.LayoutParams(0, -2, 1));
        Switch s = new Switch(this);
        s.setChecked(on);
        s.setOnCheckedChangeListener((b, v) -> cb.on(v));
        row.addView(s);
        parent.addView(row, lp(-1, -2, 0, px(4), 0, px(4)));
        return s;
    }

    /** 一排放 n 個、平均分寬 */
    private void wrap(LinearLayout box, List<View> views, int n) {
        box.removeAllViews();
        LinearLayout row = null;
        for (int i = 0; i < views.size(); i++) {
            if (i % n == 0) {
                row = new LinearLayout(this);
                box.addView(row, lp(-1, -2, 0, 0, 0, px(6)));
            }
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
            p.setMargins(i % n == 0 ? 0 : px(6), 0, 0, 0);
            row.addView(views.get(i), p);
        }
        if (row != null && views.size() % n != 0)
            for (int k = views.size() % n; k < n; k++) row.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
    }
}
