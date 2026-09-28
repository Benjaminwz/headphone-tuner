package io.github.benjaminwz.headphonetuner;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.View;

/** EQ 曲線：橘線＝整體效果（校正＋細調）、咖啡色虛線＝你的細調，跟電腦版一樣 */
public class CurveView extends View {
    private double[] total, style;
    private boolean on = true;
    private final Paint grid = new Paint(Paint.ANTI_ALIAS_FLAG), text = new Paint(Paint.ANTI_ALIAS_FLAG),
            line = new Paint(Paint.ANTI_ALIAS_FLAG), fill = new Paint(Paint.ANTI_ALIAS_FLAG), dash = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float d;

    public CurveView(Context c) {
        super(c);
        d = c.getResources().getDisplayMetrics().density;
        grid.setColor(MainActivity.LINE);
        grid.setStrokeWidth(d);
        text.setColor(MainActivity.SUB);
        text.setTextSize(10 * d);
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeWidth(2.5f * d);
        line.setStrokeJoin(Paint.Join.ROUND);
        fill.setColor(MainActivity.FILL);
        dash.setStyle(Paint.Style.STROKE);
        dash.setStrokeWidth(1.5f * d);
        dash.setColor(MainActivity.TWEAK);
        dash.setPathEffect(new DashPathEffect(new float[]{5 * d, 4 * d}, 0));
    }

    void set(double[] total, double[] style, boolean on) {
        this.total = total;
        this.style = style;
        this.on = on;
        invalidate();
    }

    private float x(double f, float L, float W) {
        return (float) (L + W * Math.log10(f / 20) / 3);
    }

    private float y(double db, float T, float H) {
        return (float) (T + H * (12 - Math.max(-12, Math.min(12, db))) / 24);
    }

    @Override
    protected void onDraw(Canvas c) {
        float L = 30 * d, R = 6 * d, T = 6 * d, B = 18 * d;
        float W = getWidth() - L - R, H = getHeight() - T - B;
        for (int db : new int[]{-12, -6, 0, 6, 12}) {
            float yy = y(db, T, H);
            c.drawLine(L, yy, L + W, yy, grid);
            c.drawText((db > 0 ? "+" : "") + db, 2 * d, yy + 4 * d, text);
        }
        double[] fs = {100, 1000, 10000};
        String[] ls = {"100", "1k", "10k"};
        for (int i = 0; i < 3; i++) {
            float xx = x(fs[i], L, W);
            c.drawLine(xx, T, xx, T + H, grid);
            c.drawText(ls[i], xx - 8 * d, getHeight() - 4 * d, text);
        }
        if (total == null) return;
        Path p = new Path(), f = new Path();
        for (int i = 0; i < Eq.FREQS.length; i++) {
            float xx = x(Eq.FREQS[i], L, W), yy = y(on ? total[i] : 0, T, H);
            if (i == 0) {
                p.moveTo(xx, yy);
                f.moveTo(xx, y(0, T, H));
            }
            p.lineTo(xx, yy);
            f.lineTo(xx, yy);
        }
        f.lineTo(x(Eq.FREQS[Eq.FREQS.length - 1], L, W), y(0, T, H));
        f.close();
        if (on) c.drawPath(f, fill);
        if (on && style != null) {
            Path s = new Path();
            for (int i = 0; i < Eq.FREQS.length; i++) {
                float xx = x(Eq.FREQS[i], L, W), yy = y(style[i], T, H);
                if (i == 0) s.moveTo(xx, yy);
                else s.lineTo(xx, yy);
            }
            c.drawPath(s, dash);
        }
        line.setColor(on ? MainActivity.ACCENT : MainActivity.SUB);
        c.drawPath(p, line);
    }
}
