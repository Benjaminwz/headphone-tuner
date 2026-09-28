package io.github.benjaminwz.headphonetuner;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 資料（風格、細調頻段；從電腦版匯出的 assets/data.json）＋ EQ 計算（跟電腦版、Equalizer APO 同一套公式）＋ AutoEQ 下載 */
final class Eq {
    static final String AUTOEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/";

    static final class Filter {
        final String type;
        final double fc, gain, q;

        Filter(String type, double fc, double gain, double q) {
            this.type = type;
            this.fc = fc;
            this.gain = gain;
            this.q = q;
        }
    }

    static final class Band {
        String name, type, hint;
        double fc, q;
    }

    static final class Style {
        String name, plain, group;
        double[] vals;
        int width, cf, room;

        boolean spatial() {
            return width != 0 || cf != 0 || room != 0;
        }
    }

    /** 耳機校正的一個選項（某單位的量測、平均、不校正） */
    static final class Base {
        final String key, label;
        final List<Filter> filters;

        Base(String key, String label, List<Filter> filters) {
            this.key = key;
            this.label = label;
            this.filters = filters;
        }
    }

    static final List<Band> BANDS = new ArrayList<>();
    static final List<String> GROUPS = new ArrayList<>();
    static final List<Style> STYLES = new ArrayList<>();
    static final Map<String, String> HELP = new LinkedHashMap<>();
    static final Map<String, List<String>> ESTIMATED = new LinkedHashMap<>();
    static final List<String> SOURCE_ORDER = new ArrayList<>();
    static final double[] FREQS = new double[200];

    static {
        for (int i = 0; i < FREQS.length; i++) FREQS[i] = 20 * Math.pow(1000, i / 199.0);
    }

    static void load(Context c) throws Exception {
        if (!STYLES.isEmpty()) return;
        JSONObject d = new JSONObject(readAll(c.getAssets().open("data.json")));
        JSONArray bands = d.getJSONArray("bands");
        for (int i = 0; i < bands.length(); i++) {
            JSONObject o = bands.getJSONObject(i);
            Band b = new Band();
            b.name = o.getString("name");
            b.type = o.getString("type");
            b.fc = o.getDouble("fc");
            b.q = o.getDouble("q");
            b.hint = o.getString("hint");
            BANDS.add(b);
        }
        JSONArray groups = d.getJSONArray("groups");
        for (int i = 0; i < groups.length(); i++) {
            JSONObject g = groups.getJSONObject(i);
            String gname = g.getString("name");
            GROUPS.add(gname);
            JSONArray st = g.getJSONArray("styles");
            for (int j = 0; j < st.length(); j++) {
                JSONObject o = st.getJSONObject(j);
                Style s = new Style();
                s.name = o.getString("name");
                s.plain = o.optString("plain");
                s.group = gname;
                JSONArray v = o.getJSONArray("vals");
                s.vals = new double[v.length()];
                for (int k = 0; k < v.length(); k++) s.vals[k] = v.getDouble(k);
                s.width = o.optInt("width");
                s.cf = o.optInt("cf");
                s.room = o.optInt("room");
                STYLES.add(s);
            }
        }
        JSONObject help = d.getJSONObject("help");
        for (Iterator<String> it = help.keys(); it.hasNext(); ) {
            String k = it.next();
            HELP.put(k, help.getString(k));
        }
        JSONObject est = d.getJSONObject("estimated");
        for (Iterator<String> it = est.keys(); it.hasNext(); ) {
            String k = it.next();
            JSONArray a = est.getJSONArray(k);
            List<String> sibs = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) sibs.add(a.getString(i));
            ESTIMATED.put(k, sibs);
        }
        JSONArray so = d.getJSONArray("source_order");
        for (int i = 0; i < so.length(); i++) SOURCE_ORDER.add(so.getString(i));
    }

    // ---------------------------------------------------------------- 計算
    /** 單一濾波器在頻率 f 的增益（dB），RBJ 公式，跟電腦版一樣 */
    static double filterDb(Filter fl, double f) {
        if (fl.gain == 0) return 0;
        double fs = 48000, A = Math.pow(10, fl.gain / 40), w0 = 2 * Math.PI * fl.fc / fs;
        double c = Math.cos(w0), al = Math.sin(w0) / (2 * fl.q);
        double b0, b1, b2, a0, a1, a2;
        if (fl.type.equals("PK")) {
            b0 = 1 + al * A; b1 = -2 * c; b2 = 1 - al * A;
            a0 = 1 + al / A; a1 = -2 * c; a2 = 1 - al / A;
        } else {
            double sq = 2 * Math.sqrt(A) * al;
            if (fl.type.equals("LSC")) {
                b0 = A * ((A + 1) - (A - 1) * c + sq); b1 = 2 * A * ((A - 1) - (A + 1) * c); b2 = A * ((A + 1) - (A - 1) * c - sq);
                a0 = (A + 1) + (A - 1) * c + sq; a1 = -2 * ((A - 1) + (A + 1) * c); a2 = (A + 1) + (A - 1) * c - sq;
            } else {
                b0 = A * ((A + 1) + (A - 1) * c + sq); b1 = -2 * A * ((A - 1) + (A + 1) * c); b2 = A * ((A + 1) + (A - 1) * c - sq);
                a0 = (A + 1) - (A - 1) * c + sq; a1 = 2 * ((A - 1) - (A + 1) * c); a2 = (A + 1) - (A - 1) * c - sq;
            }
        }
        double w = -2 * Math.PI * f / fs, cr = Math.cos(w), ci = Math.sin(w), c2r = Math.cos(2 * w), c2i = Math.sin(2 * w);
        double nr = b0 + b1 * cr + b2 * c2r, ni = b1 * ci + b2 * c2i;
        double dr = a0 + a1 * cr + a2 * c2r, di = a1 * ci + a2 * c2i;
        return 10 * Math.log10((nr * nr + ni * ni) / (dr * dr + di * di));
    }

    static double at(List<Filter> fl, double f) {
        double s = 0;
        for (Filter x : fl) s += filterDb(x, f);
        return s;
    }

    static double[] curve(List<Filter> fl) {
        double[] out = new double[FREQS.length];
        for (int i = 0; i < FREQS.length; i++) out[i] = at(fl, FREQS[i]);
        return out;
    }

    static List<Filter> styleFilters(double[] vals) {
        List<Filter> out = new ArrayList<>();
        for (int i = 0; i < BANDS.size() && i < vals.length; i++) {
            Band b = BANDS.get(i);
            if (vals[i] != 0) out.add(new Filter(b.type, b.fc, vals[i], b.q));
        }
        return out;
    }

    static double max(double[] a) {
        double m = -1e9;
        for (double v : a) m = Math.max(m, v);
        return m;
    }

    // ---------------------------------------------------------------- 耳機校正選項
    static List<Filter> parseFilters(JSONArray a) throws Exception {
        List<Filter> out = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) {
            JSONArray f = a.getJSONArray(i);
            out.add(new Filter(f.getString(0), f.getDouble(1), f.getDouble(2), f.getDouble(3)));
        }
        return out;
    }

    /** 跟電腦版 set_headphone 一樣：第一份來源＝推薦、其餘各一個、兩份以上再加「多份平均」、最後「不校正」 */
    static List<Base> bases(JSONObject hp) {
        List<Base> out = new ArrayList<>();
        try {
            JSONArray srcs = hp == null ? new JSONArray() : hp.optJSONArray("sources");
            if (srcs == null) srcs = new JSONArray();
            boolean est = hp != null && ESTIMATED.containsKey(hp.optString("name"));
            String[] keys = {"autoeq", "src2", "src3"};
            List<Filter> avg = new ArrayList<>();
            for (int i = 0; i < srcs.length() && i < 3; i++) {
                JSONArray s = srcs.getJSONArray(i);
                List<Filter> fl = parseFilters(s.getJSONArray(1));
                boolean rec = i == 0 && !est;
                out.add(new Base(keys[i], s.getString(0) + (rec ? "（推薦）" : " 量測"), fl));
                for (Filter f : fl) avg.add(new Filter(f.type, f.fc, f.gain / Math.min(3, srcs.length()), f.q));
            }
            if (srcs.length() >= 2) out.add(new Base("avg", est ? "多份平均（推薦）" : "多份平均（最不偏）", avg));
        } catch (Exception ignored) {
        }
        out.add(new Base("none", "不校正（耳機原味）", new ArrayList<>()));
        return out;
    }

    static String defaultBase(JSONObject hp) {
        List<Base> bs = bases(hp);
        boolean est = hp != null && ESTIMATED.containsKey(hp.optString("name"));
        for (Base b : bs) if (b.key.equals(est ? "avg" : "autoeq")) return b.key;
        return "none";
    }

    // ---------------------------------------------------------------- AutoEQ 下載
    static String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        in.close();
        return new String(bo.toByteArray(), StandardCharsets.UTF_8);
    }

    static String get(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(20000);
        c.setReadTimeout(30000);
        if (c.getResponseCode() != 200) throw new Exception("HTTP " + c.getResponseCode());
        return readAll(c.getInputStream());
    }

    /** AutoEQ 耳機清單（30 天內下載過就用快取）→ 型號 → [來源, 路徑] */
    static Map<String, List<String[]>> loadIndex(Context c) throws Exception {
        File f = new File(c.getFilesDir(), "INDEX.md");
        String text;
        if (f.exists() && System.currentTimeMillis() - f.lastModified() < 30L * 86400000L) {
            text = readAll(new FileInputStream(f));
        } else {
            text = get(AUTOEQ_RAW + "INDEX.md");
            FileOutputStream o = new FileOutputStream(f);
            o.write(text.getBytes(StandardCharsets.UTF_8));
            o.close();
        }
        Map<String, List<String[]>> models = new LinkedHashMap<>();
        Matcher m = Pattern.compile("^- \\[(.+)\\]\\((\\./.+)\\) by (.+)$", Pattern.MULTILINE).matcher(text);
        while (m.find()) {
            String src = m.group(3).split(" on ")[0].trim();
            List<String[]> l = models.get(m.group(1));
            if (l == null) models.put(m.group(1), l = new ArrayList<>());
            l.add(new String[]{src, m.group(2).substring(2)});
        }
        // 同一款耳機在資料庫裡寫法不同（大小寫、空格，例如 AirPods Pro2／Airpods Pro 2）→ 合併，量測份數才多；
        // 顯示名稱取大寫、空格最多的寫法
        Map<String, List<String>> names = new LinkedHashMap<>();
        Map<String, List<String[]>> ents = new LinkedHashMap<>();
        for (Map.Entry<String, List<String[]>> e : models.entrySet()) {
            String k = norm(e.getKey());
            if (!names.containsKey(k)) {
                names.put(k, new ArrayList<String>());
                ents.put(k, new ArrayList<String[]>());
            }
            names.get(k).add(e.getKey());
            ents.get(k).addAll(e.getValue());
        }
        models = new LinkedHashMap<>();
        for (String k : names.keySet()) {
            String best = null;
            for (String n : names.get(k)) if (best == null || nice(n) > nice(best)) best = n;
            models.put(best, ents.get(k));
        }
        // 資料庫沒量過的型號：用同系列兄弟機推估（兩支交錯取）
        for (Map.Entry<String, List<String>> e : ESTIMATED.entrySet()) {
            List<List<String[]>> lists = new ArrayList<>();
            for (String sib : e.getValue()) {
                List<String[]> l = new ArrayList<>();
                List<String[]> got = models.get(sib);
                String tag = sib.contains("-") ? sib.substring(sib.lastIndexOf('-') + 1) : sib.substring(sib.lastIndexOf(' ') + 1);
                if (got != null) for (String[] s : got) l.add(new String[]{s[0] + "（" + tag + "）", s[1]});
                lists.add(l);
            }
            List<String[]> ent = new ArrayList<>();
            for (int i = 0; ; i++) {
                boolean any = false;
                for (List<String[]> l : lists) if (i < l.size()) { ent.add(l.get(i)); any = true; }
                if (!any) break;
            }
            if (!ent.isEmpty()) models.put(e.getKey(), ent);
        }
        return models;
    }

    static int rank(String src) {
        int i = SOURCE_ORDER.indexOf(src);
        return i < 0 ? SOURCE_ORDER.size() : i;
    }

    /** 下載這支耳機最多 3 個不同來源的校正 → JSON：{"name", "sources": [[來源, [[類型, 頻率, 增益, Q], ...]], ...]} */
    static JSONObject downloadHeadphone(String name, List<String[]> entries) throws Exception {
        List<String[]> sorted = new ArrayList<>(entries);
        java.util.Collections.sort(sorted, (a, b) -> rank(a[0]) - rank(b[0]));
        Set<String> seen = new LinkedHashSet<>();
        JSONArray out = new JSONArray();
        Exception last = null;
        Pattern p = Pattern.compile("ON (LSC|HSC|PK) Fc ([\\d.]+) Hz Gain ([-\\d.]+) dB Q ([\\d.]+)");
        for (String[] e : sorted) {
            if (seen.contains(e[0]) || out.length() >= 3) continue;
            String link = e[1];
            String leaf = URLDecoder.decode(link.substring(link.lastIndexOf('/') + 1).replace("+", "%2B"), "UTF-8");
            String file = URLEncoder.encode(leaf + " ParametricEQ.txt", "UTF-8").replace("+", "%20");
            try {
                String text = get(AUTOEQ_RAW + link + "/" + file);
                JSONArray fl = new JSONArray();
                Matcher m = p.matcher(text);
                while (m.find()) {
                    JSONArray f = new JSONArray();
                    f.put(m.group(1)).put(Double.parseDouble(m.group(2))).put(Double.parseDouble(m.group(3)))
                            .put(Double.parseDouble(m.group(4)));
                    fl.put(f);
                }
                if (fl.length() > 0) {
                    seen.add(e[0]);
                    out.put(new JSONArray().put(e[0]).put(fl));
                }
            } catch (Exception ex) {
                last = ex;
            }
        }
        if (out.length() == 0) throw last != null ? last : new Exception("沒有可用的資料");
        return new JSONObject().put("name", name).put("sources", out);
    }

    static int nice(String n) {
        int up = 0, sp = 0;
        for (char c : n.toCharArray()) {
            if (Character.isUpperCase(c)) up++;
            if (c == ' ') sp++;
        }
        return up * 100 + sp;
    }

    static String norm(String s) {
        return s.toLowerCase().replaceAll("[^0-9a-z]", "");
    }
}
