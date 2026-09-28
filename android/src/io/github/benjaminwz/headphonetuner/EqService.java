package io.github.benjaminwz.headphonetuner;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.media.audiofx.AudioEffect;
import android.media.audiofx.DynamicsProcessing;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.Map;

/**
 * 在背景持續套用等化器。
 * 全域模式：接在「整支手機的輸出」（session 0），所有 App 都有效；有些手機不允許，就自動改用
 * 個別 App 模式：播放 App 開始播放時會廣播自己的音效代號，收到就接上去（Tidal、多數音樂 App 都會廣播）。
 * 音色用 DynamicsProcessing 的前置等化器（64 段，依電腦版同一條曲線取樣）＋輸入增益（預留音量）＋保險用的限幅器。
 */
public class EqService extends Service {
    static final String PREFS = "tuner";
    static final int BANDS = 64;
    static volatile String status = "還沒啟動";
    static volatile boolean running = false;

    private DynamicsProcessing global;
    private final Map<Integer, DynamicsProcessing> sessions = new HashMap<>();
    private boolean globalFailed = false;

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context c, Intent i) {
            int id = i.getIntExtra(AudioEffect.EXTRA_AUDIO_SESSION, -1);
            if (id <= 0) return;
            if (AudioEffect.ACTION_OPEN_AUDIO_EFFECT_CONTROL_SESSION.equals(i.getAction())) {
                if (useGlobal()) return;  // 全域已經在處理，不要疊兩次
                if (!sessions.containsKey(id)) {
                    try {
                        sessions.put(id, create(id));
                    } catch (Exception ignored) {
                    }
                }
                apply();
            } else {
                DynamicsProcessing dp = sessions.remove(id);
                if (dp != null) dp.release();
                apply();
            }
        }
    };

    /** 每段的中心：20 Hz～20 kHz 對數平均分 64 段 */
    static double[] centers() {
        double[] c = new double[BANDS];
        for (int i = 0; i < BANDS; i++) c[i] = 20 * Math.pow(1000, i / (double) (BANDS - 1));
        return c;
    }

    /** 每段的上緣（DynamicsProcessing 用上緣定義每一段）：相鄰中心的幾何平均，最後一段到 22 kHz */
    static float[] cutoffs() {
        float[] c = new float[BANDS];
        for (int i = 0; i < BANDS; i++) c[i] = (float) (20 * Math.pow(1000, (i + 0.5) / (BANDS - 1)));
        c[BANDS - 1] = 22000;
        return c;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("eq", "等化器運作中", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new Notification.Builder(this, "eq")
                .setSmallIcon(R.drawable.ic_fg)
                .setContentTitle("耳機調音台")
                .setContentText("等化器運作中，點一下打開調音台")
                .setContentIntent(open)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1, n);
        IntentFilter f = new IntentFilter();
        f.addAction(AudioEffect.ACTION_OPEN_AUDIO_EFFECT_CONTROL_SESSION);
        f.addAction(AudioEffect.ACTION_CLOSE_AUDIO_EFFECT_CONTROL_SESSION);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, f, Context.RECEIVER_EXPORTED);
        else registerReceiver(receiver, f);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        apply();
        return START_STICKY;
    }

    private JSONObject applied() {
        try {
            return new JSONObject(getSharedPreferences(PREFS, MODE_PRIVATE).getString("applied", "{}"));
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private boolean useGlobal() {
        return !globalFailed && !"session".equals(applied().optString("mode", "global"));
    }

    private DynamicsProcessing create(int session) {
        DynamicsProcessing.Config.Builder b = new DynamicsProcessing.Config.Builder(
                DynamicsProcessing.VARIANT_FAVOR_FREQUENCY_RESOLUTION, 2, true, BANDS, false, 0, false, 0, true);
        DynamicsProcessing.Eq eq = new DynamicsProcessing.Eq(true, true, BANDS);
        float[] c = cutoffs();
        for (int i = 0; i < BANDS; i++) eq.setBand(i, new DynamicsProcessing.EqBand(true, c[i], 0f));
        b.setPreEqAllChannelsTo(eq);
        // 保險用：萬一還是超過滿格，只在最後 1 dB 內輕輕壓住，不會聽到壓縮感
        b.setLimiterAllChannelsTo(new DynamicsProcessing.Limiter(true, true, 0, 1f, 60f, 10f, -1f, 0f));
        DynamicsProcessing dp = new DynamicsProcessing(Integer.MAX_VALUE, session, b.build());
        dp.setEnabled(true);
        return dp;
    }

    /** 把 MainActivity 算好的曲線（每一段的增益）和預留音量套上去 */
    private void apply() {
        JSONObject a = applied();
        JSONArray g = a.optJSONArray("gains");
        boolean on = a.optBoolean("on", true);
        float pre = (float) a.optDouble("preamp", 0);
        if (useGlobal() && global == null) {
            try {
                global = create(0);
                for (DynamicsProcessing dp : sessions.values()) dp.release();
                sessions.clear();
            } catch (Exception e) {
                globalFailed = true;  // 這支手機不給接全域 → 改個別 App
            }
        } else if (!useGlobal() && global != null) {
            global.release();
            global = null;
        }
        float[] c = cutoffs();
        for (DynamicsProcessing dp : all()) {
            try {
                dp.setEnabled(on);
                if (g != null && g.length() == BANDS) {
                    for (int i = 0; i < BANDS; i++)
                        dp.setPreEqBandAllChannelsTo(i, new DynamicsProcessing.EqBand(true, c[i], (float) g.optDouble(i, 0)));
                }
                dp.setInputGainAllChannelsTo(pre);
            } catch (Exception ignored) {
            }
        }
        if (global != null) status = "運作中（整支手機）";
        else if (globalFailed) status = "這支手機不允許整支套用，改接播放 App：已接上 " + sessions.size() + " 個";
        else status = "個別 App 模式：已接上 " + sessions.size() + " 個播放 App";
    }

    private Iterable<DynamicsProcessing> all() {
        java.util.List<DynamicsProcessing> l = new java.util.ArrayList<>(sessions.values());
        if (global != null) l.add(global);
        return l;
    }

    @Override
    public void onDestroy() {
        running = false;
        status = "已關閉";
        try {
            unregisterReceiver(receiver);
        } catch (Exception ignored) {
        }
        for (DynamicsProcessing dp : all()) dp.release();
        sessions.clear();
        global = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent i) {
        return null;
    }

    static void start(Context c) {
        c.startForegroundService(new Intent(c, EqService.class));
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, EqService.class));
    }
}
