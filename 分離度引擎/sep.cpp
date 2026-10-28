// 分離度引擎：Equalizer APO 直接載入的 VST2 外掛（只用 C++ 標準函式庫，不需要 VST SDK）
//
// 做法（頻域的主成分／環境音分解：Avendano & Jot 2004, Merimaa 等 2007, Faller 2006）
// 1. 短時傅立葉轉換：約 21 ms 的 Hann 窗、重疊 75%（取樣率越高窗越長，時間長度固定）
// 2. 每個頻率格算左右的共變異（約 50 ms 平滑，頻率方向再平均約半個聽覺頻帶 ERB）→ 主成分＝這附近最主要的聲音
//    （某個樂器）和它在左右的位置，剩下的＝環境音、殘響（左右不相關的部分），原封不動
//    第 1 版只看單一頻率格、30 ms：估計值一格一格跳 → 推的量跟著跳，聽起來有顆粒感（頻域處理的「音樂雜訊」）
// 3. 把主成分往外推：靠中間的拉開最多、已經在最左右的不動、正中間（人聲）不動
//    「方向性」低（很多聲音混在一起、或是擴散的殘響）的頻率格推得少 → 不會亂飄
// 4. 再加上對應位置的兩耳時間差（最多 0.2 ms），只在 1 kHz 以下（到 2 kHz 漸漸淡掉）：耳朵只在這裡用得到時間差
//    （Rayleigh 雙重理論）；第 1 版高頻也加，相位跟著推的量晃動 → 粗糙
// 5. 150 Hz 以下、24 kHz 以上不處理（低音不分方向、超音波沒有樂器）；強度 0 時輸出＝輸入（只有固定延遲）
//
// 參數：Strength（0–1）。Equalizer APO 設定：VSTPlugin: Library "...\sep_v1.dll" ChunkData "<base64 的 strength=0.60>"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

typedef std::complex<double> cd;

struct AEffect;
typedef intptr_t (*audioMasterCallback)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
typedef intptr_t (*DispatcherProc)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
typedef void (*ProcessProc)(AEffect*, float**, float**, int32_t);
typedef void (*ProcessDoubleProc)(AEffect*, double**, double**, int32_t);
typedef void (*SetParameterProc)(AEffect*, int32_t, float);
typedef float (*GetParameterProc)(AEffect*, int32_t);

struct AEffect {  // VST 2.4 的 ABI（公開的結構，跟 vestige.h 相同）
    int32_t magic;
    DispatcherProc dispatcher;
    ProcessProc process;
    SetParameterProc setParameter;
    GetParameterProc getParameter;
    int32_t numPrograms, numParams, numInputs, numOutputs, flags;
    intptr_t resvd1, resvd2;
    int32_t initialDelay, realQualities, offQualities;
    float ioRatio;
    void* object;
    void* user;
    int32_t uniqueID, version;
    ProcessProc processReplacing;
    ProcessDoubleProc processDoubleReplacing;
    char future[56];
};

enum {
    effOpen = 0, effClose = 1, effGetProgramName = 5, effGetParamLabel = 6, effGetParamDisplay = 7, effGetParamName = 8,
    effSetSampleRate = 10, effSetBlockSize = 11, effMainsChanged = 12, effGetChunk = 23, effSetChunk = 24,
    effCanBeAutomated = 26, effGetPlugCategory = 35, effGetEffectName = 45, effGetVendorString = 47,
    effGetProductString = 48, effGetVendorVersion = 49, effCanDo = 51, effGetVstVersion = 58
};
const int32_t kMagic = ('V' << 24) | ('s' << 16) | ('t' << 8) | 'P';
const int32_t kFlagsCanReplacing = 1 << 4, kFlagsProgramChunks = 1 << 5;

const double kPi = 3.14159265358979323846;
const double kFrameSec = 1024.0 / 48000.0;   // 窗長約 21 ms
const double kSmoothSec = 0.050;             // 共變異平滑
const double kErbFrac = 0.5;                 // 頻率方向平均的寬度（聽覺頻帶 ERB 的幾倍；0.3–1 顆粒感都一樣低，越窄分得越開）
const double kItdMax = 0.0002;               // 最大兩耳時間差（秒）
const double kItdLo = 1000.0, kItdHi = 2000.0;  // 時間差只加在這以下（中間漸漸淡掉）
const double kTopHz = 24000.0;               // 這以上不處理
const double kExpand = 1.5;                  // 強度 1 時，中間附近的位置變成 2.5 倍
const double kLowCut0 = 150.0, kLowCut1 = 250.0;

struct Sep {
    AEffect fx;
    std::atomic<float> strength{0.6f};
    char chunk[64];
    double fs = 0;
    int N = 0, H = 0, fresh = 0;
    std::vector<double> win, in[2], ola[2], q[2];
    std::vector<cd> Z, tw;
    std::vector<int> rev;
    std::vector<double> pll, prr, gate, omega, itdw;
    std::vector<cd> plr, L, R;
    std::vector<int> hw;  // 每個頻率格往左右各平均幾格（約 1 ERB）
    int kTop = 0;
    double alpha = 0;
    int qn = 0, qr = 0;  // 輸出佇列（已完成的樣本數、讀取位置）

    void setup(double rate) {
        if (rate <= 0) rate = 48000;
        fs = rate;
        int n = 256;
        while (n < kFrameSec * fs * 0.999) n <<= 1;
        N = n;
        H = N / 4;
        win.assign(N, 0);
        for (int i = 0; i < N; i++) win[i] = 0.5 - 0.5 * std::cos(2 * kPi * i / N);
        for (int c = 0; c < 2; c++) {
            in[c].assign(N, 0);
            ola[c].assign(N, 0);
            q[c].assign(2 * N, 0);
        }
        Z.assign(N, 0);
        tw.resize(N / 2);
        for (int i = 0; i < N / 2; i++) tw[i] = std::polar(1.0, -2 * kPi * i / N);
        rev.resize(N);
        int bits = 0;
        while ((1 << bits) < N) bits++;
        for (int i = 0; i < N; i++) {
            int r = 0;
            for (int b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b);
            rev[i] = r;
        }
        int K = N / 2 + 1;
        pll.assign(K, 0);
        prr.assign(K, 0);
        plr.assign(K, 0);
        L.assign(K, 0);
        R.assign(K, 0);
        gate.assign(K, 0);
        omega.assign(K, 0);
        itdw.assign(K, 0);
        hw.assign(K, 0);
        kTop = std::min(K - 2, (int)(kTopHz * N / fs));
        for (int k = 0; k < K; k++) {
            double f = k * fs / N;
            double x = (std::log(std::max(f, 1e-9)) - std::log(kLowCut0)) / std::log(kLowCut1 / kLowCut0);
            x = std::min(1.0, std::max(0.0, x));
            gate[k] = std::sin(kPi / 2 * x) * std::sin(kPi / 2 * x);
            omega[k] = 2 * kPi * f;
            double y = (std::log(std::max(f, 1e-9)) - std::log(kItdLo)) / std::log(kItdHi / kItdLo);
            y = std::min(1.0, std::max(0.0, y));
            itdw[k] = std::cos(kPi / 2 * y) * std::cos(kPi / 2 * y);
            double erb = 24.7 * (4.37 * f / 1000 + 1);                 // Glasberg & Moore 1990
            hw[k] = (int)(0.5 * kErbFrac * erb / (fs / N));
        }
        alpha = std::exp(-(double)H / (kSmoothSec * fs));
        fresh = 0;
        qn = qr = 0;
        fx.initialDelay = N - 1;  // 同一個呼叫裡收滿 H 個就輸出 → 實際延遲 N−1 個樣本
    }

    void fft(bool inverse) {
        for (int i = 0; i < N; i++)
            if (i < rev[i]) std::swap(Z[i], Z[rev[i]]);
        for (int len = 2; len <= N; len <<= 1) {
            int step = N / len;
            for (int i = 0; i < N; i += len)
                for (int j = 0; j < len / 2; j++) {
                    cd w = tw[j * step];
                    if (inverse) w = std::conj(w);
                    cd u = Z[i + j], v = Z[i + j + len / 2] * w;
                    Z[i + j] = u + v;
                    Z[i + j + len / 2] = u - v;
                }
        }
    }

    void frame() {
        double s = strength.load();
        for (int i = 0; i < N; i++) Z[i] = cd(in[0][i] * win[i], in[1][i] * win[i]);
        fft(false);
        int K = N / 2 + 1;
        std::vector<cd>& Y = Z;  // 就地改寫：先把左右分出來
        for (int k = 0; k < K; k++) {
            cd a = Z[k], b = std::conj(Z[(N - k) % N]);
            L[k] = (a + b) * 0.5;
            R[k] = (a - b) * cd(0, -0.5);
        }
        int kEnd = std::min(K - 2, kTop + hw[kTop]);
        for (int k = 1; k <= kEnd; k++) {
            cd l = L[k], r = R[k];
            pll[k] = alpha * pll[k] + (1 - alpha) * std::norm(l);
            prr[k] = alpha * prr[k] + (1 - alpha) * std::norm(r);
            plr[k] = alpha * plr[k] + (1 - alpha) * l * std::conj(r);
        }
        for (int k = 1; k <= kTop; k++) {
            double g = gate[k] * s;
            if (g <= 0) continue;
            cd l = L[k], r = R[k];
            double a = 0, b = 0;
            cd c = 0;
            for (int j = std::max(1, k - hw[k]); j <= std::min(kEnd, k + hw[k]); j++) {  // 頻率方向平均（約 1 ERB）
                a += pll[j];
                b += prr[j];
                c += plr[j];
            }
            double tr = a + b;
            if (!(tr > 1e-24)) continue;
            double d = std::sqrt((a - b) * (a - b) + 4 * std::norm(c));
            double l1 = 0.5 * (tr + d), l2 = 0.5 * (tr - d);
            cd vL, vR;
            if (std::abs(c) > 1e-9 * tr) { vL = l1 - b; vR = std::conj(c); }
            else if (a >= b) { vL = 1; vR = 0; }
            else { vL = 0; vR = 1; }
            double nv = std::sqrt(std::norm(vL) + std::norm(vR));
            vL /= nv;
            vR /= nv;
            double p = std::norm(vL) - std::norm(vR);              // +1＝最左、−1＝最右
            double dirn = (l1 - l2) / (l1 + l2 + 1e-30);            // 方向性
            double kk = kExpand * g * dirn;
            double p2 = p * (1 + kk * (1 - std::fabs(p)));
            p2 = std::min(1.0, std::max(-1.0, p2));
            cd sp = std::conj(vL) * l + std::conj(vR) * r;          // 主成分
            cd aL = l - vL * sp, aR = r - vR * sp;                   // 環境音（不動）
            double aL0 = std::abs(vL), aR0 = std::abs(vR);
            cd uL = (aL0 > 1e-12 ? vL / aL0 : cd(1, 0)) * std::sqrt(0.5 * (1 + p2));
            cd uR = (aR0 > 1e-12 ? vR / aR0 : cd(1, 0)) * std::sqrt(0.5 * (1 - p2));
            double tau = kItdMax * g * p2 * itdw[k];                // 偏左 → 右耳晚到（只在低頻）
            if (tau > 0) uR *= std::polar(1.0, -omega[k] * tau);
            else if (tau < 0) uL *= std::polar(1.0, omega[k] * tau);
            L[k] = uL * sp + aL;
            R[k] = uR * sp + aR;
        }
        for (int k = 0; k < K; k++) {  // 組回 L + iR 的頻譜 → 逆轉換的實部＝左、虛部＝右
            Y[k] = L[k] + cd(0, 1) * R[k];
            if (k > 0 && k < N / 2) Y[N - k] = std::conj(L[k]) + cd(0, 1) * std::conj(R[k]);
        }
        fft(true);
        double sc = 1.0 / (N * 1.5);  // 逆轉換的 1/N；Hann² 在重疊 75% 時加起來＝1.5
        for (int i = 0; i < N; i++) {
            ola[0][i] += Y[i].real() * win[i] * sc;
            ola[1][i] += Y[i].imag() * win[i] * sc;
        }
        for (int c = 0; c < 2; c++) {  // 前 H 個已經完整 → 放進輸出佇列
            for (int i = 0; i < H; i++) q[c][(qr + qn + i) % (2 * N)] = ola[c][i];
            std::memmove(ola[c].data(), ola[c].data() + H, sizeof(double) * (N - H));
            std::memset(ola[c].data() + N - H, 0, sizeof(double) * H);
        }
        qn += H;
    }

    void process(float** inputs, float** outputs, int32_t n) {
        if (!N) {
            for (int c = 0; c < 2; c++)
                if (outputs[c] != inputs[c]) std::memcpy(outputs[c], inputs[c], sizeof(float) * n);
            return;
        }
        for (int i = 0; i < n; i++) {
            for (int c = 0; c < 2; c++) in[c][N - H + fresh] = inputs[c][i];
            if (++fresh == H) {
                frame();
                for (int c = 0; c < 2; c++) std::memmove(in[c].data(), in[c].data() + H, sizeof(double) * (N - H));
                fresh = 0;
            }
            float o[2] = {0, 0};
            if (qn > 0) {
                o[0] = (float)q[0][qr];
                o[1] = (float)q[1][qr];
                qr = (qr + 1) % (2 * N);
                qn--;
            }
            outputs[0][i] = o[0];
            outputs[1][i] = o[1];
        }
    }
};

static void setText(void* ptr, const char* s, size_t cap) {
    if (!ptr) return;
    std::strncpy((char*)ptr, s, cap - 1);
    ((char*)ptr)[cap - 1] = 0;
}

static intptr_t dispatcher(AEffect* e, int32_t op, int32_t index, intptr_t value, void* ptr, float opt) {
    Sep* s = (Sep*)e->object;
    switch (op) {
    case effClose:
        delete s;
        return 1;
    case effSetSampleRate:
        s->setup(opt);
        return 1;
    case effMainsChanged:
        if (value && s->fs <= 0) s->setup(48000);
        return 1;
    case effGetParamName:
        setText(ptr, "Strength", 8);
        return 1;
    case effGetParamLabel:
        setText(ptr, "%", 8);
        return 1;
    case effGetParamDisplay: {
        char b[16];
        std::snprintf(b, sizeof b, "%d", (int)std::lround(s->strength.load() * 100));
        setText(ptr, b, 8);
        return 1;
    }
    case effGetChunk:
        std::snprintf(s->chunk, sizeof s->chunk, "strength=%.3f", s->strength.load());
        *(void**)ptr = s->chunk;
        return (intptr_t)std::strlen(s->chunk);
    case effSetChunk: {
        char b[64] = {0};
        std::memcpy(b, ptr, (size_t)std::min<intptr_t>(value, 63));
        const char* p = std::strstr(b, "strength=");
        if (p) s->strength.store((float)std::min(1.0, std::max(0.0, std::atof(p + 9))));
        return 1;
    }
    case effCanBeAutomated:
        return 1;
    case effGetPlugCategory:
        return 1;  // kPlugCategEffect
    case effGetEffectName:
    case effGetProductString:
        setText(ptr, "BlueFish Separation", 32);
        return 1;
    case effGetVendorString:
        setText(ptr, "BlueFish", 64);
        return 1;
    case effGetVendorVersion:
        return 1000;
    case effGetVstVersion:
        return 2400;
    default:
        return 0;
    }
}

static void processReplacing(AEffect* e, float** in, float** out, int32_t n) { ((Sep*)e->object)->process(in, out, n); }
static void setParameter(AEffect* e, int32_t i, float v) {
    if (i == 0) ((Sep*)e->object)->strength.store(std::min(1.0f, std::max(0.0f, v)));
}
static float getParameter(AEffect* e, int32_t i) { return i == 0 ? ((Sep*)e->object)->strength.load() : 0.0f; }

extern "C" __declspec(dllexport) AEffect* VSTPluginMain(audioMasterCallback) {
    Sep* s = new Sep();
    AEffect& e = s->fx;
    std::memset(&e, 0, sizeof e);
    e.magic = kMagic;
    e.dispatcher = dispatcher;
    e.setParameter = setParameter;
    e.getParameter = getParameter;
    e.numParams = 1;
    e.numInputs = e.numOutputs = 2;
    e.flags = kFlagsCanReplacing | kFlagsProgramChunks;
    e.object = s;
    e.uniqueID = ('B' << 24) | ('F' << 16) | ('s' << 8) | 'p';
    e.version = 1000;
    e.processReplacing = processReplacing;
    e.process = processReplacing;
    e.ioRatio = 1.0f;
    s->setup(48000);
    return &e;
}
