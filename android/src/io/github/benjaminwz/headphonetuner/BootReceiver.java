package io.github.benjaminwz.headphonetuner;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import org.json.JSONObject;

/** 開機後：上次是開著的就自動恢復等化器 */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())) return;
        try {
            JSONObject s = new JSONObject(c.getSharedPreferences(EqService.PREFS, Context.MODE_PRIVATE).getString("state", "{}"));
            if (s.optBoolean("enabled", false)) EqService.start(c);
        } catch (Exception ignored) {
        }
    }
}
