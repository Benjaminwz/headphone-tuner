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
//    （人聲集中例外：低音也分出正中間的那份，見 mode 5）
//    排布（調音台照風格給）：width＝直接擺位的舞台寬度（角度 ×width）、near＝正中間的聲音的房間反射大小（人聲遠近）
//
// 6. 環繞（mode）：同一個外掛在設定檔裡載兩次，分解完全一樣（兩邊加起來＝只有分離度時的輸出）：
//    mode=1 只輸出前方＝主成分＋留在前方的環境音（√(1−amb)），mode=2 只輸出環境音（√amb，150 Hz 以下、24 kHz 以上沒有）
//    → 調音台把 mode=2 那份送到側後方 ±110° 的虛擬環繞喇叭。兩份能量加起來跟原本一樣
//    兩聲道分出來的環境音左右幾乎反相（人聲在中間時只剩「左減右」）→ 右邊再過一個固定的全通濾波
//    （相位 ±2.4 弧度隨頻率起伏、群延遲最多約 2.4 ms）把左右打散，兩顆環繞喇叭才不會互相抵消（Kendall 1995 的去相關）
//
// 7. 直接擺位（mode=4，第 3 代）：虛擬喇叭原本是兩顆喇叭「湊」出中間的樂器（幻象聲像：兩耳各收到兩顆喇叭、
//    時間不同 → 梳狀干涉、位置跟頭型有關）。這裡改成每個頻率格的主成分照它的位置（正切定律：兩顆 ±30° 喇叭會
//    湊出來的角度，Bauer 1961）直接套那個方向的頭部量測 → 輸出就是兩耳的直達聲；環境音照兩顆喇叭的方向。
//    頭部量測由調音台做成表（table=…：每 1° 一組、最小相位＋兩耳各自的延遲，Kulkarni 等 1999 證明這樣聽起來
//    跟原本的量測一樣），房間反射另外由調音台摺積（同一個外掛 mode=1 的喇叭訊號）→ 延遲完全一樣
//
// 8. 動態處理（mode=3，時間域、沒有延遲）：
//    不刺耳（harsh=1–3）：3.5 kHz（刺耳）、7 kHz（齒音）各一個頻帶，跟 300 Hz–2.5 kHz 比（動態等化，de-esser 的作法）。
//    第 2 版（2026-11-03）：第 1 版只跟固定門檻比，實測 8 首歌「輕」有 15% 的時間在壓、7 kHz 一帶整首平均少 1.2 dB
//    （最多的一首少 2 dB）→ 壓到原音。現在這些條件都要成立才壓：
//      1. 比固定門檻亮（偏暗的歌不動）
//      2. 比這首歌最近的「平常」（中位數）亮：3.5k 8／6／4 dB、7k 11／9／7 dB 以上（輕／中／強）→ 歌本身的亮度算原音
//      3. 只有這一段突出：多出來的能量上面的頻帶沒有跟著多（鈸、小鼓、沙鈴是整片一起亮 → 原音，不壓；
//         齒音只有 5–10 kHz、尖銳的人聲只有 3–5 kHz）
//      4. 音樂在它平常的大小（比平常小 15 dB 以上的安靜段落漸漸不壓）
//    壓的量：軟膝（門檻附近慢慢開始）、輕 2:1 最多 3 dB、中 3:1 最多 6 dB、強 4:1 最多 9 dB
//    第 3 版（2026-11-03，開了之後聽起來糊、粗糙）：第 2 版壓的量直接跟著能量包絡走，
//    人聲每個音高週期都會讓它抖一下（實測「中」動作時在 15–300 Hz 抖約 ±0.6 dB）＝快速的音量起伏＝聽起來糙、細節糊掉。
//    改成「一下就壓、慢慢放」（2 ms 壓、60 ms 放），壓的量只跟著句子、齒音走，不跟著音高抖
//    實測（8 首歌、48 kHz）：輕 在一般的歌壓超過 1 dB 的時間 0.5%（3.5k）／2%（7k，大多是齒音），第 1 版 15%／16%；
//    鈸幾乎不壓（第 1 版壓 1–2 dB）
//    遊戲（game=1）：150 Hz 以下大聲時壓（爆炸、4:1）、整體太大聲時壓（槍聲、3:1）、1–5 kHz 小聲時往上拉
//    （腳步、換彈：最多 +9 dB，−70 dBFS 以下不拉，底噪不會被放大；拉完的峰值不超過 −1 dBFS）
//    左右聲道用同一個增益 → 方向不變。每段都是「原音＋(增益−1)×那個頻帶」（Regalia & Mitra 1987）：增益 1 時逐位元原音
//
// 參數：Equalizer APO 設定：VSTPlugin: Library "...\sep_v1.dll" ChunkData "<base64 的 strength=0.60;mode=1;amb=0.60>"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <vector>
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <sddl.h>
#pragma comment(lib, "advapi32.lib")

typedef std::complex<double> cd;
typedef std::complex<float> cf;

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
const double kStrengthMax = 2.0;             // 強度上限（調音台的「超強」超過 1；位置最多到最左、最右，不會反過來）
const double kLowCut0 = 150.0, kLowCut1 = 250.0;
const double kSpkDeg = 30.0;                 // 虛擬喇叭 ±30°（直接擺位：最左、最右的聲音就在喇叭的位置）
// 推開、加時間差、分出環境音、直接擺位都只用在「一個聲音明顯主導」的頻率格（方向性 ≥ kDirHi 全用、≤ kDirLo 不用）：
// 好幾個聲音混在同一格
// （搖滾左右兩把吉他＋中間人聲）時主成分是妥協的方向 → 兩把吉他各有一半被拉到正中間跟人聲擠在一起
// （聽起來人聲被壓扁）。實測（人聲＋左右吉他，每 50 ms 人聲的兩耳音量差）：
// 舊的人聲一直被吉他拉著飄（起伏 1.8 dB），照方向性之後 0.14 dB。這種格：直接擺位照兩顆喇叭原樣、
// 耳機的分離度不推也不加時間差、環繞不把它當環境音送到後面（裡面其實是別的樂器）
// 單一聲音＋殘響的方向性約 0.8–1，兩三個聲音約 0.2–0.75
const double kDirLo = 0.5, kDirHi = 0.85;
// 人聲集中（喇叭模式，focus＞0）：人聲會散開，是因為房間反射到兩耳不一樣（側牆、房間不對稱、後段殘響兩耳不相關：
// 早期側向反射讓聲像變寬，Barron & Marshall 1981）。正中間的聲音不從 mode 1 那一路送到反射，改由 mode 5 送出、
// 調音台用「兩耳一樣」的反射摺積 → 反射的量、時間、音色都在（遠近、房間感不變），只是兩耳一樣 → 像耳機模式一樣凝聚。
// 正中間的聲音＝中（(左＋右)/2）那一份，兩邊一樣的人聲只在中裡面；兩邊的吉他、殘響的側那一份照樣是兩耳不同的反射。
// 一個聲音主導、而且偏一邊的格（旁邊的單一樂器）漸漸不算：|p| ≤ kFocusIn 全用、≥ kFocusOut 不用。
// 實測（人聲＋左右吉他，2026-11-07）：人聲兩耳相似度 0.74 → 0.96（耳機模式 1.00）、左右晃動 0.29 → 0.14 dB（耳機 0.15），
// 吉他 0.24 → 0.21（空間感不變）。用「左右共同的部分」（維納濾波）只抓得到約四成人聲（0.77），比不上整份
const double kFocusIn = 0.1, kFocusOut = 0.25;  // 兩耳差約 0.9 dB／2.2 dB
// 貼耳（ear＞0，喇叭模式）：人聲集中之後人聲還是在「前面的喇叭那裡」——直達聲套了 0° 的頭部量測（耳廓的濾波＝聲音在
// 頭外面前方）、反射告訴大腦有距離，跟關掉喇叭模式（耳機）的人聲比起來不夠貼耳。
// → 正中間的聲音那一份完全不經過虛擬喇叭：mode 4、mode 1 都扣掉，mode 6 原封不動送出、加在補償之後（跟耳機模式一樣：
// 沒有頭部量測、沒有房間、沒有補償），只延遲 0° 的耳朵延遲跟直達聲對齊；樂器、背景照樣是喇叭和房間
const double kEarIn = 0.25, kEarOut = 0.5;      // 主成分的位置 |p| 到 kEarIn 全拿、到 kEarOut 不拿
// 貼耳的拖影（人聲有時候像拖著影子）。實測（旋律人聲＋左右撥弦吉他，人聲停了之後 15–75 ms 的
// 尾巴，耳機模式 −34.5 dB）：舊的 −23 dB，三路都有——人聲跟吉他混在一起的格，沒分乾淨的那一點人聲照樣進虛擬房間、
// 帶著房間聲拖在後面（最大的一份）。抓得快一點（20、30 ms）字頭多抓一點，但字中間少抓、總的沒變好 → 平滑照 50 ms。
// 解法：有人聲的格照人聲佔的比例（×2）把整格的中擋在房間外（rx＝2）→ 尾巴 −30 dB；沒有人聲的格不動，吉他的房間聲只少 0.4 dB
const double kEarSmoothSec = 0.05;
// 再加一道「這一瞬間」的檢查：人聲在的那一刻左右一模一樣（側＝(左−右)/2 幾乎沒有），左右兩把吉他主導的那一刻側跟中一樣大。
// 維納濾波只看平均（人聲唱的時候吉他的「中」有一部分跟著被拿進耳朵裡）→ 用約 8 ms 的中、側能量：
// 拿的量 ×(1 − 側/中)（只在左右真的一樣的瞬間拿；偏一邊的樂器前面已經扣乾淨，不受影響）。實測吉他漏進耳朵 14% → 12%
const double kMsSec = 0.008;
// 人聲大小（voc＞0：調音台「人聲大小」那一份 mode 6）：「正中間的聲音」不等於人聲——正中間還有貝斯、大鼓、小鼓、鈸，
// 以前一起被當成人聲（去人聲連貝斯、大鼓一起拿掉，只聽人聲裡一直有鼓）。
// ① 頻段：人聲的基音約 100 Hz 以上、齒音到約 9 kHz（Audacity 的人聲分離預設也是 120 Hz–9 kHz）→ 這以外不拿
// ② 鼓：打擊聲在頻率上是平的一片、時間上很短；人聲是一條一條的泛音、時間上連續 → 中值濾波分開（Fitzgerald 2010 HPSS）：
//    時間中值 H（只用這一格和之前的幾格，不加延遲）、頻率中值 P，拿 H²/(H²＋P²)
const int kVocNhMax = 15;
// AI 人聲（mode 6、ai＝1、dly＝秒；公開版的調音台還沒用到）：本機另外跑的 AI 程式（例如 BS-RoFormer、用顯示卡）分得準很多，但要看到
// 前後幾秒才分得好 → 外掛把原音寫進共用記憶體、AI 程式每秒算一次寫回人聲；這一路（和調音台用 Delay 補的 L R）整條
// 多晚 dly 秒。AI 程式沒開、來不及、或還沒寫到 → 用上面的 DSP 人聲（也晚 dly 秒，時間一樣對齊），切換時 20 ms 淡入淡出
// 共用記憶體（Global\HPTunerVoxAI，int64 欄位）：0 魔術字、1 版本代號 gen、2 現在寫的外掛 owner、3 取樣率（double）、
// 4 環的長度 cap、5 輸出比輸入晚幾個樣本 delay、6 已寫進的原音 inW、7 AI 寫好的人聲從哪裡開始 outStart、8 寫到哪裡 outW、
// 9 AI 程式的心跳（GetTickCount64）；256 位元組之後：原音環 float[cap][2]、人聲環 float[cap][2]（位置＝從頭算第幾個樣本）
const wchar_t* const kAiName = L"Global\\HPTunerVoxAI";
const wchar_t* const kAiNameLocal = L"Local\\HPTunerVoxAI";  // 測試用（一般程式建不了 Global）
const int64_t kAiCapMax = (int64_t)1 << 22;                  // 384 kHz 也有約 10 秒
const size_t kAiHdr = 256;
const double kAiRingSec = 8.0, kAiFadeSec = 0.02;

// ---------------------------------------------------------------- 動態處理（mode=3）
struct Biquad {  // 轉置直接二型，每個聲道各自的狀態
    double b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1[2] = {0, 0}, z2[2] = {0, 0};
    void bandpass(double fs, double f0, double q) {  // RBJ 帶通（中心 0 dB）＝(1 − 二階全通)/2
        double w = 2 * kPi * f0 / fs, al = std::sin(w) / (2 * q), a0 = 1 + al;
        b0 = al / a0, b1 = 0, b2 = -al / a0, a1 = -2 * std::cos(w) / a0, a2 = (1 - al) / a0;
        z1[0] = z1[1] = z2[0] = z2[1] = 0;
    }
    void highpass(double fs, double f0, double q) {  // RBJ 高通
        double w = 2 * kPi * f0 / fs, al = std::sin(w) / (2 * q), cw = std::cos(w), a0 = 1 + al;
        b0 = (1 + cw) / 2 / a0, b1 = -(1 + cw) / a0, b2 = (1 + cw) / 2 / a0, a1 = -2 * cw / a0, a2 = (1 - al) / a0;
        z1[0] = z1[1] = z2[0] = z2[1] = 0;
    }
    inline double run(int c, double x) {
        double y = b0 * x + z1[c];
        z1[c] = b1 * x - a1 * y + z2[c];
        z2[c] = b2 * x - a2 * y;
        return y;
    }
};

struct Lowpass1 {  // 一階低通＝(1 + 一階全通)/2
    double c = 0, x1[2] = {0, 0}, y1[2] = {0, 0};
    void set(double fs, double fc) {
        double t = std::tan(kPi * fc / fs);
        c = (t - 1) / (t + 1);
        x1[0] = x1[1] = y1[0] = y1[1] = 0;
    }
    inline double run(int ch, double x) {
        double ap = c * x + x1[ch] - c * y1[ch];
        x1[ch] = x, y1[ch] = ap;
        return 0.5 * (x + ap);
    }
};

struct Env {  // 能量包絡：上升、下降各自的時間常數
    double a = 0, r = 0, e = 0;
    void set(double fs, double att, double rel) {
        a = std::exp(-1 / (att * fs)), r = std::exp(-1 / (rel * fs)), e = 0;
    }
    inline void run(double p) { e = p > e ? a * e + (1 - a) * p : r * e + (1 - r) * p; }
};

static inline double db10(double p) { return 10 * std::log10(p + 1e-20); }
static inline double clampd(double x, double lo, double hi) { return std::min(hi, std::max(lo, x)); }

struct Median {  // 中位數追蹤：比目前的估計大就往上一小步、小就往下一小步 → 停在中間。
    double v = 0, step = 0;  // 每次只動一點點 → 很大聲的那幾下拉不動它（跟平均不一樣）
    void set(double init, double perSec, double rate) { v = init, step = perSec / rate; }
    inline void run(double x) { v += x > v ? step : -step; }
};

// 不刺耳的等級：比這首歌的中位數多 m1（3.5k）、m2（7k）dB 才算刺耳（7k 的起伏本來就大：齒音、鈸）；
// slope＝壓的比例（0.5＝2:1）、mx＝最多壓幾 dB、rise＝中位數每秒最多動幾 dB（強：慢慢適應 → 一直刺耳的段落也會一直壓）
struct HarshLevel { double m1, m2, slope, mx, rise; };
const HarshLevel kHarsh[4] = {{0, 0, 0, 0, 1}, {8, 11, 0.5, 3, 3}, {6, 9, 2.0 / 3, 6, 2}, {4, 7, 0.75, 9, 1}};
const double kKnee = 4;         // 軟膝寬度（dB）
const double kQuietDb = -70;    // 中頻比這小＝幾乎沒聲音：不壓、不更新；連續 0.5 秒＝換歌了 → 重新開始
const double kSoftBelow = 15;   // 比這首歌平常的大小小 15 dB 以上就漸漸不壓（再小 6 dB 完全不壓）

static inline double knee(double x) {  // 超過門檻多少 → 要壓的量（還沒乘比例）
    if (x <= -kKnee / 2) return 0;
    if (x >= kKnee / 2) return x;
    return (x + kKnee / 2) * (x + kKnee / 2) / (2 * kKnee);
}

const double kLookSec = 0.002;  // 動態處理先看 2 ms：增益在聲音到之前就調好（齒音、槍聲的開頭不會漏掉）
const double kCeil = 0.891;     // 遊戲往上拉之後的峰值上限（−1 dBFS）

struct Dyn {
    int harsh = 0, game = 0;
    Biquad bp1, bp2, hp3a, hp3b, bpr, bpu;
    Biquad s1a, s1b, s2a, s2b;  // 不刺耳的偵測用四階（兩個二階串起來）：二階的裙邊會把大很多的中頻漏進來，齒音看起來只多 5–10 dB
    Lowpass1 low;
    Env e1, e2, e3, er, elo, eall, eup;
    double pk = 0, pkr = 0, gs = 0, upA = 0, upR = 0, upCur = 0;
    double g1 = 1, g2 = 1, glo = 1, gbb = 1, gup = 1, t1 = 1, t2 = 1, tlo = 1, tbb = 1, tup = 1;
    Median m1, m2, m3, lvl;  // 不刺耳：這首歌 3.5k、7k、11k 以上跟中頻比的中位數，中頻平常的大小
    double rate = 0;    // 每秒算幾次目標增益
    double s1 = 0, s2 = 0, aAtt = 0, aRel = 0;  // 平滑後真正要壓的 dB：一下就壓（aAtt）、慢慢放（aRel）
    int hset = -1, quiet = 0, quietMax = 0;
    int cnt = 0, D = 0, wp = 0;
    std::vector<double> dl[5][2];  // 延遲 D 的原音、低頻、腳步頻帶、刺耳、齒音

    void setup(double fs) {
        bp1.bandpass(fs, 3500, 1.0);   // 刺耳區（耳道共振、等響曲線最敏感的地方）
        bp2.bandpass(fs, 7000, 2.0);   // 齒音
        s1a.bandpass(fs, 3500, 0.7), s1b.bandpass(fs, 3500, 0.7);  // 偵測：跟上面一樣寬（約 2.2–5.5k），1 kHz 少 5 dB、500 Hz 少 11 dB
        s2a.bandpass(fs, 7000, 1.4), s2b.bandpass(fs, 7000, 1.4);  // 偵測：約 5.6–8.8k，2 kHz 少 10 dB、1 kHz 少 17 dB
        double fa = std::min(11000.0, 0.35 * fs);  // 11 kHz 以上（四階巴特沃斯，齒音漏進來很少）：只用來判斷是不是整片一起變亮
        hp3a.highpass(fs, fa, 0.5412), hp3b.highpass(fs, fa, 1.3066);
        bpr.bandpass(fs, 866, 0.39);   // 參考：300 Hz–2.5 kHz
        bpu.bandpass(fs, 2500, 0.7);   // 腳步、換彈：約 1–5 kHz
        low.set(fs, 150);              // 爆炸的低頻
        e1.set(fs, 0.002, 0.03), e2.set(fs, 0.002, 0.03), e3.set(fs, 0.002, 0.03), er.set(fs, 0.002, 0.03);
        elo.set(fs, 0.005, 0.25), eall.set(fs, 0.002, 0.15), eup.set(fs, 0.002, 0.1);
        pk = 0, pkr = std::exp(-1 / (0.15 * fs)), gs = 1 - std::exp(-1 / (0.0005 * fs));
        upA = 1 - std::exp(-32 / (0.25 * fs)), upR = 1 - std::exp(-32 / (0.005 * fs)), upCur = 0;
        g1 = g2 = glo = gbb = gup = t1 = t2 = tlo = tbb = tup = 1;
        rate = fs / 32, quietMax = (int)(0.5 * rate), quiet = 0, hset = -1;
        aAtt = 1 - std::exp(-1 / (0.002 * rate)), aRel = 1 - std::exp(-1 / (0.06 * rate)), s1 = s2 = 0;
        cnt = 0, wp = 0, D = (int)std::lround(kLookSec * fs);
        for (auto& a : dl)
            for (auto& b : a) b.assign(D + 1, 0.0);
    }

    double harshOff() const { return harsh == 1 ? 2.0 : harsh == 2 ? 0.0 : -2.0; }  // 固定門檻：輕高一點、強低一點

    void harshInit() {  // 開始、換歌、換等級：從一般歌曲的典型值開始，之後跟著這首歌走
        const HarshLevel& h = kHarsh[harsh];
        m1.set(-10, h.rise, rate), m2.set(-17, h.rise, rate), m3.set(-25, h.rise, rate), lvl.set(-30, 3, rate);
        hset = harsh;
    }

    void targets() {  // 每 32 個樣本算一次目標增益
        if (harsh) {
            if (hset != harsh) harshInit();
            const HarshLevel& h = kHarsh[harsh];
            double ref = db10(er.e), q1 = db10(e1.e) - ref, q2 = db10(e2.e) - ref, q3 = db10(e3.e) - ref, r1 = 0, r2 = 0;
            if (ref < kQuietDb) {  // 幾乎沒聲音：比例沒有意義
                if (quiet < quietMax && ++quiet == quietMax) harshInit();
            } else {
                quiet = 0;
                lvl.run(ref);
                double gate = clampd((ref - lvl.v + kSoftBelow + 6) / 6, 0, 1);  // 安靜的段落不壓
                if (gate > 0.5) m1.run(q1), m2.run(q2), m3.run(q3);             // 也不算進「平常」
                double x1 = std::min(q1 - (-7 + harshOff()), q1 - m1.v - h.m1);
                double x2 = std::min(q2 - (-12 + harshOff()), q2 - m2.v - h.m2);
                // 只有這一段突出才算：比平常多出來的能量（跟中頻比），上面的頻帶多出來的跟它比
                auto more = [](double q, double m) { return std::max(0.0, std::pow(10, q / 10) - std::pow(10, m / 10)); };
                double a1 = more(q1, m1.v), a2 = more(q2, m2.v), a3 = more(q3, m3.v);
                double w1 = clampd((0.6 - (a2 + a3) / (a1 + 1e-20)) / 0.4, 0, 1);  // 尖銳：7k 以上多的 < 20% 全壓、> 60% 不壓
                double w2 = clampd((0.8 - a3 / (a2 + 1e-20)) / 0.5, 0, 1);         // 齒音：11k 以上多的 < 30% 全壓、> 80% 不壓
                r1 = std::min(h.mx, h.slope * knee(x1)) * gate * w1;
                r2 = std::min(h.mx, h.slope * knee(x2)) * gate * w2;
            }
            s1 += (r1 > s1 ? aAtt : aRel) * (r1 - s1);
            s2 += (r2 > s2 ? aAtt : aRel) * (r2 - s2);
            t1 = std::pow(10, -s1 / 20), t2 = std::pow(10, -s2 / 20);
        } else {
            t1 = t2 = 1, s1 = s2 = 0;
        }
        if (game) {
            double rl = clampd((db10(elo.e) + 30) * 0.75, 0, 12);        // 低頻 −30 dBFS 以上 4:1
            double rb = clampd((db10(eall.e) + 20) * (2.0 / 3), 0, 9);   // 整體 −20 dBFS 以上 3:1
            double lu = db10(eup.e), up = lu < -35 ? std::min(9.0, (-35 - lu) * 0.5) : 0.0;  // −35 以下往上拉（1:2）
            up *= clampd((lu + 70) / 6, 0, 1);                              // −70 dBFS 以下不拉
            double lim = std::max(0.0, -1 - 20 * std::log10(pk + 1e-12) + rb);  // 拉完的峰值 ≤ −1 dBFS
            upCur += (up > upCur ? upA : upR) * (up - upCur);
            upCur = std::min(upCur, lim);
            tlo = std::pow(10, -rl / 20), tbb = std::pow(10, -rb / 20), tup = std::pow(10, upCur / 20);
        } else {
            tlo = tbb = tup = 1, upCur = 0;
        }
    }

    void process(float** in, float** out, int32_t n) {
        for (int i = 0; i < n; i++) {
            double x[2] = {in[0][i], in[1][i]}, b1[2], b2[2], b3[2], s1[2], s2[2], br[2], lo[2], bu[2];
            for (int c = 0; c < 2; c++) {
                b1[c] = bp1.run(c, x[c]);
                b2[c] = bp2.run(c, x[c]);
                b3[c] = hp3b.run(c, hp3a.run(c, x[c]));
                s1[c] = s1b.run(c, s1a.run(c, x[c]));
                s2[c] = s2b.run(c, s2a.run(c, x[c]));
                br[c] = bpr.run(c, x[c]);
                lo[c] = low.run(c, x[c]);
                bu[c] = bpu.run(c, x[c]);
            }
            e1.run(0.5 * (s1[0] * s1[0] + s1[1] * s1[1]));
            e2.run(0.5 * (s2[0] * s2[0] + s2[1] * s2[1]));
            e3.run(0.5 * (b3[0] * b3[0] + b3[1] * b3[1]));
            er.run(0.5 * (br[0] * br[0] + br[1] * br[1]));
            elo.run(0.5 * (lo[0] * lo[0] + lo[1] * lo[1]));
            eall.run(0.5 * (x[0] * x[0] + x[1] * x[1]));
            eup.run(0.5 * (bu[0] * bu[0] + bu[1] * bu[1]));
            double p = std::max(std::fabs(x[0]), std::fabs(x[1]));
            pk = p > pk ? p : pkr * pk;  // 這 2 ms 內會出現的峰值（偵測沒有延遲、聲音有）
            if (++cnt >= 32) {
                cnt = 0;
                targets();
            }
            g1 += gs * (t1 - g1), g2 += gs * (t2 - g2), glo += gs * (tlo - glo), gbb += gs * (tbb - gbb), gup += gs * (tup - gup);
            if (game) gup = std::min(gup, std::max(1.0, kCeil / (gbb * pk + 1e-12)));  // 大聲的來了：往上拉馬上收掉
            int rp = (wp + 1) % (D + 1);
            for (int c = 0; c < 2; c++) {
                double v[5] = {x[c], lo[c], bu[c], b1[c], b2[c]};
                for (int j = 0; j < 5; j++) dl[j][c][wp] = v[j];
                double xd = dl[0][c][rp], base = gbb * (xd + (glo - 1) * dl[1][c][rp] + (g1 - 1) * dl[3][c][rp] +
                                                      (g2 - 1) * dl[4][c][rp]);
                double y = base + gbb * (gup - 1) * dl[2][c][rp];
                if (std::fabs(y) > kCeil && std::fabs(y) > std::fabs(base))  // 保險：往上拉的那份不准超過 −1 dBFS
                    y = std::fabs(base) > kCeil ? base : std::copysign(kCeil, y);
                out[c][i] = (float)y;
            }
            wp = rp;
        }
    }
};

// ---------------------------------------------------------------- 直接擺位的頭部量測表（mode=4，調音台做的）
// 檔案：'BFH1'、取樣率、N、K、方向數（int32）、第一個角度、角度間隔（float，度，左＝正）、保留（int32）；
// 接著 M[方向][耳][K]（complex<float>，最小相位、已含音色補償）、tau[方向][耳]（float，秒，相對正前方到達頭中心）
struct Table {
    int K = 0, nAz = 0;
    double az0 = 0, step = 1;
    std::vector<cf> M;
    std::vector<float> tau;
    std::vector<cd> spk;  // 兩顆喇叭（+30°、−30°）到兩耳：[LL, RL, LR, RR][K]

    cd h(int a, int e, int k, double w) const {
        return cd(M[((size_t)a * 2 + e) * K + k]) * std::polar(1.0, -w * tau[a * 2 + e]);
    }
};

struct Sep {
    AEffect fx;
    std::atomic<float> strength{0.6f};
    std::atomic<int> mode{0};       // 0＝一般、1＝只要前方、2＝只要環境音（環繞）、3＝動態處理、4＝直接擺位、5＝正中間的聲音
    std::atomic<float> amb{0.0f};   // 環繞：環境音送到側後方的比例
    std::atomic<float> focus{0.0f};  // 人聲集中：正中間的聲音改走兩耳一樣的反射（mode 1 扣掉、mode 5 送出）
    std::atomic<float> width{1.0f};  // 排布：舞台寬度（mode 4，直接擺位的角度 ×width，最多到表的 ±45°）
    std::atomic<float> nearg{1.0f};  // 排布：正中間的聲音的房間反射大小（mode 5 ×nearg；小於 1＝人聲比樂團近）
    std::atomic<float> ear{0.0f};    // 貼耳：正中間的聲音直接給兩耳的量（mode 1、4 扣掉，mode 6 送出）
    std::atomic<float> esm{(float)kEarSmoothSec};  // 貼耳抓人聲用的平滑時間（秒）
    std::atomic<float> post{1.0f};  // 貼耳「這一瞬間」檢查的強度（0＝不檢查）
    std::atomic<int> rx{2};         // 貼耳：不進房間的範圍（0＝只有送進耳朵的、1＝認出來的人聲、2＝有人聲的格照比例）
    std::atomic<float> rxg{2.0f};   // rx＝2 的倍數
    std::atomic<float> voc{0.0f};   // 人聲大小：mode 6 只拿人聲（頻段＋濾掉鼓），0＝正中間的聲音全拿（聽喇叭的貼耳）
    std::atomic<float> vph{1.0f}, vwh{300.0f}, vlo{220.0f}, vhi{8000.0f};  // 濾鼓的量、頻率中值寬度（Hz）、頻段（全拿的範圍）
    std::atomic<int> vnh{7};        // 時間中值用幾格
    std::atomic<float> ai{0.0f};    // 人聲大小用 AI（mode 6）
    std::atomic<float> dly{0.0f};   // 整條多晚幾秒（等 AI；0＝不等）
    std::atomic<bool> ailoc{false};  // 測試用：共用記憶體用 Local（一般程式裡）
    HANDLE aiMap = nullptr;
    volatile int64_t* aiH = nullptr;  // 共用記憶體的欄位
    float *aiIn = nullptr, *aiOut = nullptr;
    int64_t aiId = 0, aiPos = 0, aiCap = 0, aiDelay = 0;
    std::vector<float> dlL, dlR;      // DSP 人聲延遲 dly 秒
    int dlLen = 0, dlPos = 0;
    double aiMix = 0;
    char chunk[512];
    char path[400] = {0};           // 直接擺位的頭部量測表
    std::atomic<Table*> tab{nullptr};
    std::vector<Table*> oldTabs;    // 換表時舊的不馬上刪（處理中可能還在用），關閉時一起刪
    Dyn dyn;
    double fs = 0;
    int N = 0, H = 0, fresh = 0;
    std::vector<double> win, in[2], ola[2], q[2];
    std::vector<cd> Z, tw;
    std::vector<int> rev;
    std::vector<double> pll, prr, gate, omega, itdw;
    std::vector<cd> decor;  // 環繞右邊的去相關全通濾波
    std::vector<cd> plr, L, R;
    std::vector<double> fll, frr;  // 貼耳用的快速共變異（跟得上每個字的開頭、結尾）
    std::vector<cd> flr;
    std::vector<double> fmm, fss;  // 貼耳用的「這一瞬間」中、側能量
    std::vector<int> hw;  // 每個頻率格往左右各平均幾格（約 1 ERB）
    std::vector<float> vhis, vmag, vtmp;  // 人聲大小：每格最近幾格的大小（環狀）、這一格的大小、算中值用
    std::vector<double> vbw;              // 人聲大小的頻段權重
    double vbwLo = -1, vbwHi = -1;
    int vpos = 0;
    int kTop = 0;
    double alpha = 0;
    int qn = 0, qr = 0;  // 輸出佇列（已完成的樣本數、讀取位置）

    ~Sep() {
        aiClose();
        delete tab.load();
        for (Table* t : oldTabs) delete t;
    }

    void aiClose() {
        if (aiH && aiH[2] == aiId) aiH[2] = 0;  // 不再寫 → AI 程式閒著
        if (aiH) UnmapViewOfFile((void*)aiH);
        if (aiMap) CloseHandle(aiMap);
        aiH = nullptr, aiMap = nullptr, aiIn = aiOut = nullptr;
    }

    // AI 人聲：延遲線、共用記憶體（setup、換參數時呼叫，不在即時的執行緒裡）
    void aiSetup() {
        int want = (fs > 0 && mode.load() == 6 && dly.load() > 0) ? (int)std::lround(dly.load() * fs) : 0;
        if (want != dlLen) {
            dlL.assign(std::max(want, 1), 0.0f);
            dlR.assign(std::max(want, 1), 0.0f);
            dlLen = want, dlPos = 0;
        }
        fx.initialDelay = mode.load() == 3 ? dyn.D : N - 1 + dlLen;
        if (!(dlLen > 0 && ai.load() > 0)) {
            aiClose();
            return;
        }
        if (!aiH) {
            // 只有 Windows 的音效程序（audiodg）裡的外掛才建共用記憶體：Equalizer APO 的檢查工具、編輯器也會載入外掛，
            // 以前它們建了一份（一般程式只能建 Local）→ AI 程式接到那份、一直等不到真的聲音（調音台顯示「啟動中」）
            static int inDg = -1;
            if (inDg < 0) {
                wchar_t exe[MAX_PATH] = {0};
                GetModuleFileNameW(nullptr, exe, MAX_PATH);
                size_t len = std::wcslen(exe);
                inDg = len >= 11 && _wcsicmp(exe + len - 11, L"audiodg.exe") == 0;
            }
            bool loc = ailoc.load();  // 測試用：在一般程式裡用 Local
            if (!inDg && !loc) return;
            size_t size = kAiHdr + (size_t)kAiCapMax * 4 * sizeof(float);
            SECURITY_ATTRIBUTES sa{sizeof sa, nullptr, FALSE};
            PSECURITY_DESCRIPTOR sd = nullptr;  // 誰都能讀寫（外掛在系統的音效程序裡、AI 程式是使用者的）
            if (ConvertStringSecurityDescriptorToSecurityDescriptorW(L"D:(A;;GA;;;WD)S:(ML;;NW;;;LW)", SDDL_REVISION_1, &sd,
                                                                     nullptr))
                sa.lpSecurityDescriptor = sd;
            DWORD hi = (DWORD)((uint64_t)size >> 32), lo = (DWORD)size;
            HANDLE h = CreateFileMappingW(INVALID_HANDLE_VALUE, &sa, PAGE_READWRITE, hi, lo, loc ? kAiNameLocal : kAiName);
            if (sd) LocalFree(sd);
            if (!h) return;
            void* v = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, size);
            if (!v) {
                CloseHandle(h);
                return;
            }
            aiMap = h;
            aiH = (volatile int64_t*)v;
            aiIn = (float*)((char*)v + kAiHdr);
            aiOut = aiIn + kAiCapMax * 2;
        }
        int64_t cap = 1;
        while (cap < (int64_t)(kAiRingSec * fs)) cap <<= 1;
        aiCap = std::min(cap, kAiCapMax);
        aiDelay = N - 1 + dlLen;
        LARGE_INTEGER qpc;
        QueryPerformanceCounter(&qpc);
        aiId = (int64_t)((uint64_t)qpc.QuadPart ^ ((uint64_t)(uintptr_t)this << 16)) | 1;
        aiPos = 0, aiMix = 0;
        aiH[2] = 0;  // 先停（改欄位時 AI 程式不要讀到一半）
        std::memcpy((void*)aiH, "HVA1", 4);
        double f = fs;
        std::memcpy((void*)(aiH + 3), &f, 8);
        aiH[4] = aiCap, aiH[5] = aiDelay, aiH[6] = 0, aiH[7] = 0, aiH[8] = 0;
        MemoryBarrier();
        aiH[1] = aiH[1] + 1;
        aiH[2] = aiId;
    }

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
        fll.assign(K, 0);
        frr.assign(K, 0);
        flr.assign(K, 0);
        fmm.assign(K, 0);
        fss.assign(K, 0);
        L.assign(K, 0);
        R.assign(K, 0);
        gate.assign(K, 0);
        omega.assign(K, 0);
        itdw.assign(K, 0);
        decor.assign(K, cd(1, 0));
        hw.assign(K, 0);
        vhis.assign((size_t)K * kVocNhMax, 0.0f);
        vmag.assign(K, 0.0f);
        vtmp.assign(K, 0.0f);
        vbw.assign(K, 0.0);
        vbwLo = vbwHi = -1;
        vpos = 0;
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
            decor[k] = std::polar(1.0, 2.405 * std::sin(2 * kPi * f / 1000.0));  // 2.405＝J0 的第一個零點 → 平均相關＝0
        }
        alpha = std::exp(-(double)H / (kSmoothSec * fs));
        fresh = 0;
        qn = qr = 0;
        dyn.setup(fs);
        fx.initialDelay = mode.load() == 3 ? dyn.D : N - 1;  // 同一個呼叫裡收滿 H 個就輸出 → 實際延遲 N−1 個樣本（動態處理：先看的 2 ms）
        loadTable();
        dlLen = -1;  // 取樣率變了：延遲線、共用記憶體重來
        aiSetup();
    }

    void loadTable() {  // 表的取樣率、窗長要跟現在的一樣，不然不用（直接擺位改成一般的喇叭訊號）
        if (!path[0] || fs <= 0) return;
        FILE* fh = std::fopen(path, "rb");
        if (!fh) return;
        char mg[4];
        int32_t hd[4], rsv;
        float a0, st;
        Table* t = nullptr;
        if (std::fread(mg, 1, 4, fh) == 4 && !std::memcmp(mg, "BFH1", 4) && std::fread(hd, 4, 4, fh) == 4 &&
            std::fread(&a0, 4, 1, fh) == 1 && std::fread(&st, 4, 1, fh) == 1 && std::fread(&rsv, 4, 1, fh) == 1 &&
            hd[0] == (int32_t)std::lround(fs) && hd[1] == N && hd[2] > 1 && hd[2] <= N / 2 + 1 && hd[3] >= 3 &&
            hd[3] <= 721 && st > 0) {
            t = new Table();
            t->K = hd[2], t->nAz = hd[3], t->az0 = a0, t->step = st;
            t->M.resize((size_t)t->nAz * 2 * t->K);
            t->tau.resize((size_t)t->nAz * 2);
            int iL = (int)std::lround((kSpkDeg - a0) / st), iR = (int)std::lround((-kSpkDeg - a0) / st);
            if (std::fread(t->M.data(), sizeof(cf), t->M.size(), fh) != t->M.size() ||
                std::fread(t->tau.data(), 4, t->tau.size(), fh) != t->tau.size() || iL < 0 || iR < 0 ||
                iL >= t->nAz || iR >= t->nAz) {
                delete t;
                t = nullptr;
            } else {
                t->spk.resize(4 * (size_t)t->K);
                for (int k = 0; k < t->K; k++) {
                    double w = 2 * kPi * k * fs / N;
                    t->spk[k] = t->h(iL, 0, k, w);              // 左喇叭 → 左耳
                    t->spk[t->K + k] = t->h(iR, 0, k, w);       // 右喇叭 → 左耳
                    t->spk[2 * t->K + k] = t->h(iL, 1, k, w);   // 左喇叭 → 右耳
                    t->spk[3 * t->K + k] = t->h(iR, 1, k, w);   // 右喇叭 → 右耳
                }
            }
        }
        std::fclose(fh);
        if (t) {
            Table* old = tab.exchange(t);
            if (old) oldTabs.push_back(old);
        }
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

    // 主成分分解（頻率格 k）：主成分 sp、它的方向 vL vR、推開後的位置 p2（+1＝最左）、環境音 aL aR；
    // 回傳 false＝這格幾乎沒聲音
    // 另外可以拿：cfOut＝主成分裡正中間的聲音佔多少、wcOut＝中（(左＋右)/2）裡正中間的聲音佔多少（能量比）、
    // phOut＝左右同不同相（1＝同相或只在一邊；左右反相 → 0：加寬過的合成器、間隔麥克風在某些頻率）
    bool decomp(int k, int kEnd, double g, cd l, cd r, cd& vL, cd& vR, double& p2, cd& sp, cd& aL, cd& aR,
                double* dirOut = nullptr, double* cfOut = nullptr, double* wcOut = nullptr, double* phOut = nullptr,
                cd* sOut = nullptr) const {
        double a = 0, b = 0;
        cd c = 0;
        for (int j = std::max(1, k - hw[k]); j <= std::min(kEnd, k + hw[k]); j++) {  // 頻率方向平均（約 1 ERB）
            a += pll[j];
            b += prr[j];
            c += plr[j];
        }
        double tr = a + b;
        if (!(tr > 1e-24)) return false;
        double d = std::sqrt((a - b) * (a - b) + 4 * std::norm(c));
        double l1 = 0.5 * (tr + d), l2 = 0.5 * (tr - d);
        if (std::abs(c) > 1e-9 * tr) { vL = l1 - b; vR = std::conj(c); }
        else if (a >= b) { vL = 1; vR = 0; }
        else { vL = 0; vR = 1; }
        double nv = std::sqrt(std::norm(vL) + std::norm(vR));
        vL /= nv;
        vR /= nv;
        double p = std::norm(vL) - std::norm(vR);              // +1＝最左、−1＝最右
        double dirn = (l1 - l2) / (l1 + l2 + 1e-30);            // 方向性
        double wd = clampd((dirn - kDirLo) / (kDirHi - kDirLo), 0, 1);  // 一個聲音主導的程度
        if (dirOut) *dirOut = wd;
        // 主成分裡正中間那個聲音（人聲）佔多少。人聲跟偏一邊的樂器在同一格時，主成分是兩者妥協的方向（偏一點），
        // 照原本的推法會把人聲一起推過去、分離度越強越偏。
        // 模型＝正中間一個＋偏一邊一個：正中間的能量＝(ab − Re(c)²)/(a + b − 2Re(c))，最多 Re(c)（左右不相關的殘響、
        // 兩邊的吉他不算）→ 正中間的聲音佔越多，推得越少；只有一個偏一邊的樂器（算出來是 0）照樣推開
        double rc = c.real(), den = a + b - 2 * rc;
        double vc = clampd(std::min(den > 1e-9 * tr ? (a * b - rc * rc) / den : rc, rc), 0, std::min(a, b));
        double cf = clampd(2 * vc / (l1 + 1e-30), 0, 1);
        if (cfOut) *cfOut = cf;
        if (wcOut) {
            double em = 0.25 * (tr + 2 * rc);
            *wcOut = em > 1e-12 * tr ? clampd(vc / em, 0, 1) : 0.0;
        }
        if (phOut) {
            double sab = std::sqrt(a * b);
            *phOut = sab > 1e-12 * tr ? clampd(1 - (std::abs(c) - std::max(rc, 0.0)) / sab, 0, 1) : 1.0;
        }
        if (sOut) {  // 正中間那個聲音本身（兩聲道維納濾波：用左右兩邊一起估，偏一邊的樂器只在一邊大 → 可以扣乾淨；
            // 只拿中的話會連樂器的「中」一起拿到）。只有正中間一個聲音時矩陣奇異 → 對角加一點（極限＝中）
            double dl = 1e-3 * tr, ap = a + dl, bp = b + dl, det = ap * bp - std::norm(c);
            *sOut = det > 1e-30 * tr * tr ? vc / det * ((bp - std::conj(c)) * l + (ap - c) * r) : 0.5 * (l + r);
        }
        double kk = kExpand * g * dirn * wd * (1 - cf) * (1 - cf);  // 平方：人聲佔一半以上就幾乎不推
        p2 = p * (1 + kk * (1 - std::fabs(p)));
        p2 = std::min(1.0, std::max(-1.0, p2));
        sp = std::conj(vL) * l + std::conj(vR) * r;             // 主成分
        aL = l - vL * sp, aR = r - vR * sp;                      // 環境音（不動）
        return true;
    }

    // 這一格要換成兩耳一樣反射的那一份＝中。一個聲音主導（wd）而且偏一邊的漸漸不算；好幾個聲音混在一起時
    // 主成分的位置是妥協的方向（跟著兩邊吉他的大小聲跳），不拿來判斷（拿來判斷的話人聲只到 0.79）。
    // 第 2 版（2026-11-07）：人聲跟偏一邊的樂器在同一格時主成分偏一點（|p|≈0.2）→ 只抓到約三成，其他七成的人聲走
    // 兩耳不同的反射；房間不對稱 → 人聲偏一邊（實測一個不對稱的房間 2–8 kHz 反射一邊多 0.9–1.4 dB）。
    // 至少要抓到「正中間那個聲音」佔中的比例（wc，正中間＋偏一邊的模型）
    static double focusW(cd vL, cd vR, double wd, double wc) {  // 人聲集中的那一份佔中（(左＋右)/2）的多少
        double pc = std::fabs(std::norm(vL) - std::norm(vR));
        return std::max(1 - wd + wd * clampd((kFocusOut - pc) / (kFocusOut - kFocusIn), 0, 1), wc);
    }
    // 貼耳：拿多少「正中間那個聲音」（decomp 的 sOut）。主成分明顯在一邊（偏一邊的樂器＋殘響：算出來的「正中間」是假的）不拿
    static double earG(cd vL, cd vR, double hp) {
        double pc = std::fabs(std::norm(vL) - std::norm(vR));
        return hp * clampd((kEarOut - pc) / (kEarOut - kEarIn), 0, 1);
    }
    // 貼耳要的「正中間那個聲音」：跟 decomp 的 sOut 同一套（正中間＋偏一邊的模型、兩聲道維納濾波），但用快速共變異
    // gp：這一瞬間的檢查（乘在送進耳朵的那份上）；回傳的是沒乘的（不進房間的那份用它：認出來的人聲都不進房間）
    cd centerEst(int k, int kEnd, cd l, cd r, double* gp = nullptr, double* wf = nullptr) const {
        double a = 0, b = 0;
        cd c = 0;
        for (int j = std::max(1, k - hw[k]); j <= std::min(kEnd, k + hw[k]); j++) {
            a += fll[j];
            b += frr[j];
            c += flr[j];
        }
        double tr = a + b;
        if (!(tr > 1e-24)) return 0;
        double rc = c.real(), den = a + b - 2 * rc;
        double vc = clampd(std::min(den > 1e-9 * tr ? (a * b - rc * rc) / den : rc, rc), 0, std::min(a, b));
        if (wf) {  // 中裡面正中間那個聲音佔多少（能量比）
            double em = 0.25 * (tr + 2 * rc);
            *wf = em > 1e-12 * tr ? clampd(vc / em, 0, 1) : 0.0;
        }
        double dl = 1e-3 * tr, ap = a + dl, bp = b + dl, det = ap * bp - std::norm(c);
        cd sh = det > 1e-30 * tr * tr ? vc / det * ((bp - std::conj(c)) * l + (ap - c) * r) : 0.5 * (l + r);
        double pk = post.load();
        if (pk > 0) {  // 這一瞬間：側能量佔中的比例越高，越不是正中間的聲音
            double pm = 0, ps = 0;
            for (int j = std::max(1, k - hw[k]); j <= std::min(kEnd, k + hw[k]); j++) {
                pm += fmm[j];
                ps += fss[j];
            }
            if (gp) *gp = pm > 1e-30 ? clampd(1 - pk * ps / pm, 0, 1) : 0.0;
        } else if (gp) {
            *gp = 1.0;
        }
        return sh;
    }

    // 人聲大小：mode 6 分出來的「正中間的聲音」（左＝右）只留人聲——頻段以外不拿、鼓（頻率上平、時間上短）濾掉
    void vocShape(int K, double vc) {
        double lo = vlo.load(), hi = vhi.load();
        if (lo != vbwLo || hi != vbwHi) {  // 頻段權重：lo／2 以下、hi×1.6 以上不拿（中間在對數頻率上 sin² 過渡）
            vbwLo = lo, vbwHi = hi;
            for (int k = 0; k < K; k++) {
                double f = std::max(k * fs / N, 1e-9);
                double a = clampd(std::log(f / (0.5 * lo)) / std::log(2.0), 0, 1);
                double b = clampd(std::log(f / hi) / std::log(1.6), 0, 1);
                vbw[k] = std::sin(kPi / 2 * a) * std::sin(kPi / 2 * a) * std::cos(kPi / 2 * b) * std::cos(kPi / 2 * b);
            }
        }
        int nh = std::max(1, std::min(kVocNhMax, vnh.load()));
        int wb = std::max(1, std::min(64, (int)std::lround(vwh.load() * N / fs)));
        double d = clampd(vph.load(), 0, 1) * std::min(1.0, vc);
        vpos = (vpos + 1) % kVocNhMax;
        for (int k = 0; k < K; k++) {
            vmag[k] = (float)std::abs(L[k]);
            vhis[(size_t)k * kVocNhMax + vpos] = vmag[k];
        }
        float hb[kVocNhMax];
        for (int k = 1; k <= kTop; k++) {
            double g = vbw[k];
            if (g > 0 && d > 0 && vmag[k] > 0) {
                for (int i = 0; i < nh; i++) hb[i] = vhis[(size_t)k * kVocNhMax + (vpos - i + kVocNhMax) % kVocNhMax];
                std::nth_element(hb, hb + nh / 2, hb + nh);
                double h = std::min((double)hb[nh / 2], (double)vmag[k]);  // 只看過去：正在變小的聲音不能比現在大
                int j0 = std::max(1, k - wb), j1 = std::min(kTop, k + wb), m = 0;
                for (int j = j0; j <= j1; j++) vtmp[m++] = vmag[j];
                std::nth_element(vtmp.begin(), vtmp.begin() + m / 2, vtmp.begin() + m);
                double p = vtmp[m / 2];
                g *= 1 - d + d * h * h / (h * h + p * p + 1e-30);
            }
            L[k] *= g;
            R[k] *= g;
        }
    }

    void frame() {
        double s = strength.load(), am = amb.load(), fo = focus.load(), nr = nearg.load(), hp = ear.load();
        int md = mode.load();
        const Table* T = (md == 4 || md == 6) ? tab.load() : nullptr;
        if (md == 4 && !T) md = 1;  // 沒有表：改成一般的喇叭訊號（至少有聲音）
        int j0 = 0;  // 正前方 0° 在表裡的位置、那裡的耳朵延遲（貼耳那一份跟直達聲對齊）
        double u0 = 0, t0 = 0;
        if (T) {
            double x0 = std::min((double)T->nAz - 1.000001, std::max(0.0, (0.0 - T->az0) / T->step));
            j0 = (int)x0;
            u0 = x0 - j0;
            t0 = 0.5 * ((1 - u0) * (T->tau[j0 * 2] + T->tau[j0 * 2 + 1]) + u0 * (T->tau[j0 * 2 + 2] + T->tau[j0 * 2 + 3]));
        }
        double fa = (md == 1 || md == 4) ? std::sqrt(1 - am) : 1.0, sa = std::sqrt(am);
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
        if (hp > 0) {
            double af = std::exp(-(double)H / (esm.load() * fs));
            for (int k = 1; k <= kEnd; k++) {
                cd l = L[k], r = R[k];
                fll[k] = af * fll[k] + (1 - af) * std::norm(l);
                frr[k] = af * frr[k] + (1 - af) * std::norm(r);
                flr[k] = af * flr[k] + (1 - af) * l * std::conj(r);
            }
            double am2 = std::exp(-(double)H / (kMsSec * fs));
            for (int k = 1; k <= kEnd; k++) {
                fmm[k] = am2 * fmm[k] + (1 - am2) * 0.25 * std::norm(L[k] + R[k]);
                fss[k] = am2 * fss[k] + (1 - am2) * 0.25 * std::norm(L[k] - R[k]);
            }
        }
        if (md == 4) {  // 直接擺位：輸出兩耳的直達聲
            const double tn = std::tan(kSpkDeg * kPi / 180), wid = width.load();
            for (int k = 0; k < K; k++) {
                if (k >= T->K) {
                    L[k] = R[k] = 0;
                    continue;
                }
                cd l = L[k], r = R[k];
                const cd *sLL = &T->spk[k], *sRL = &T->spk[T->K + k], *sLR = &T->spk[2 * T->K + k],
                         *sRR = &T->spk[3 * T->K + k];
                cd oL = *sLL * l + *sRL * r, oR = *sLR * l + *sRR * r;  // 兩顆喇叭的直達聲
                double w = (k >= 1 && k <= kTop) ? gate[k] : 0.0;
                cd vL, vR, sp, aL, aR;
                double p2, dn = 0, cf = 0, wc = 0, ph = 1;
                bool need = w > 0 || (hp > 0 && k >= 1 && k <= kTop);  // 貼耳：低音也要分（正中間的貝斯、男聲的低音）
                cd sh = 0;
                bool ok = need && decomp(k, kEnd, gate[k] * s, l, r, vL, vR, p2, sp, aL, aR, &dn, &cf, &wc, &ph);
                if (ok && hp > 0) {
                    double gp = 1;
                    sh = centerEst(k, kEnd, l, r, &gp);
                    sh *= gp;
                    double bg = earG(vL, vR, hp);
                    if (bg > 0) {  // 貼耳的那一份不從這裡出（mode 6 直接給兩耳）：剩下的照原本的做法（同一組權重 → 線性）
                        cd e = bg * sh;
                        l -= e;
                        r -= e;
                        sp = std::conj(vL) * l + std::conj(vR) * r;
                        aL = l - vL * sp;
                        aR = r - vR * sp;
                        oL = *sLL * l + *sRL * r;
                        oR = *sLR * l + *sRR * r;
                    }
                }
                if (ok && w > 0) {
                    double fk = std::sqrt(1 - am * dn);  // 環繞：只把有把握的環境音分到後面
                    double gl = std::sqrt(0.5 * (1 + p2)), gr = std::sqrt(0.5 * (1 - p2));
                    double th = std::atan(tn * (gl - gr) / (gl + gr + 1e-30)) * 180 / kPi * wid;  // 正切定律 × 舞台寬度
                    double x = std::min((double)T->nAz - 1.000001, std::max(0.0, (th - T->az0) / T->step));
                    int i0 = (int)x;
                    double u = x - i0;
                    size_t b0 = (size_t)i0 * 2 * T->K + k, b1 = b0 + 2 * (size_t)T->K;
                    cd mL = (1 - u) * cd(T->M[b0]) + u * cd(T->M[b1]);
                    cd mR = (1 - u) * cd(T->M[b0 + T->K]) + u * cd(T->M[b1 + T->K]);
                    double tL = (1 - u) * T->tau[i0 * 2] + u * T->tau[i0 * 2 + 2];
                    double tR = (1 - u) * T->tau[i0 * 2 + 1] + u * T->tau[i0 * 2 + 3];
                    // 推開、加寬只改位置、不改大小：越旁邊近耳收到的越多（頭的遮擋＋耳廓），實測偏 6 dB 的樂器在超強＋寬 1.3
                    // 時 4 kHz 大 2.3 dB、500 Hz 大 1.8 dB（有些背景樂器聽起來太大聲）→ 兩耳加起來的能量
                    // 照回它原本的位置（沒推、沒加寬）擺出來的大小
                    double gq = 1.0;
                    if (std::fabs(p2 - (std::norm(vL) - std::norm(vR))) > 1e-6 || std::fabs(wid - 1) > 1e-6) {
                        double p0 = std::norm(vL) - std::norm(vR);
                        double g0 = std::sqrt(0.5 * (1 + p0)), h0 = std::sqrt(0.5 * (1 - p0));
                        double t0d = std::atan(tn * (g0 - h0) / (g0 + h0 + 1e-30)) * 180 / kPi;
                        double z = std::min((double)T->nAz - 1.000001, std::max(0.0, (t0d - T->az0) / T->step));
                        int q0 = (int)z;
                        double v = z - q0;
                        size_t e0 = (size_t)q0 * 2 * T->K + k, e1 = e0 + 2 * (size_t)T->K;
                        double P0 = std::norm((1 - v) * cd(T->M[e0]) + v * cd(T->M[e1])) +
                                    std::norm((1 - v) * cd(T->M[e0 + T->K]) + v * cd(T->M[e1 + T->K]));
                        double P1 = std::norm(mL) + std::norm(mR);
                        gq = P1 > 1e-30 ? clampd(std::sqrt(P0 / P1), 0.5, 2.0) : 1.0;
                    }
                    cd dL = gq * mL * std::polar(1.0, -omega[k] * tL) * sp + fk * (*sLL * aL + *sRL * aR);
                    cd dR = gq * mR * std::polar(1.0, -omega[k] * tR) * sp + fk * (*sLR * aL + *sRR * aR);
                    // 好幾個聲音混在一起（dn 低）、左右反相的主成分（ph 低：加寬過的合成器，擺到一個方向會變成正中間的
                    // 單聲道）：照喇叭原樣
                    double wv = dn * ph;
                    cd eL = wv * dL + (1 - wv) * oL, eR = wv * dR + (1 - wv) * oR;
                    // 正中間的聲音跟偏一邊的樂器在同一格：主成分是兩者妥協的方向，整格擺過去人聲會被拉向樂器（實測樂器在
                    // 左／右時人聲 2–8 kHz 偏 ±1.2–1.8 dB，強度 0 也一樣）。改成正中間那一份（中 × wc）直接放在 0°、
                    // 其他照兩顆喇叭原樣（線性 → 誰都不會被拉走、樂器的位置跟真的喇叭一樣）；
                    // 只有正中間（cf＝1，就是 0° 直接擺位）或完全沒有正中間的聲音（cf＝0）的格跟原本一樣
                    double mx = 1 - (1 - cf) * (1 - cf);
                    if (mx > 0 && wc > 0) {
                        cd cc = 0.5 * wc * (l + r);
                        size_t c0 = (size_t)j0 * 2 * T->K + k, c1 = c0 + 2 * (size_t)T->K;
                        cd nL = (1 - u0) * cd(T->M[c0]) + u0 * cd(T->M[c1]);
                        cd nR = (1 - u0) * cd(T->M[c0 + T->K]) + u0 * cd(T->M[c1 + T->K]);
                        double sL = (1 - u0) * T->tau[j0 * 2] + u0 * T->tau[j0 * 2 + 2];
                        double sR = (1 - u0) * T->tau[j0 * 2 + 1] + u0 * T->tau[j0 * 2 + 3];
                        cd hL = oL + (std::sqrt(2.0) * nL * std::polar(1.0, -omega[k] * sL) - *sLL - *sRL) * cc -
                                (1 - fk) * (*sLL * aL + *sRL * aR);
                        cd hR = oR + (std::sqrt(2.0) * nR * std::polar(1.0, -omega[k] * sR) - *sLR - *sRR) * cc -
                                (1 - fk) * (*sLR * aL + *sRR * aR);
                        eL = mx * hL + (1 - mx) * eL;
                        eR = mx * hR + (1 - mx) * eR;
                    }
                    oL = w * eL + (1 - w) * oL;
                    oR = w * eR + (1 - w) * oR;
                }
                L[k] = oL;
                R[k] = oR;
            }
        } else {
            // 人聲集中（mode 5、mode 1 扣掉的那份）低音也要：低音不分方向，但正中間的貝斯、大鼓、男聲的低音一樣要
            // 兩耳一樣的反射（第 1 版 150 Hz 以下沒有 → 走房間不對稱的反射，實測正中間的聲音 125 Hz 偏左 1.1 dB）
            bool fz = md == 5 || md == 6 || (md == 1 && (fo > 0 || hp > 0));
            if (md == 2 || md == 5 || md == 6)  // 只要環境音／正中間的聲音：超音波沒有；環境音低音也沒有
                for (int k = 0; k < K; k++)
                    if (k < 1 || k > kTop || (md == 2 && gate[k] <= 0)) L[k] = R[k] = 0;
            for (int k = 1; k <= kTop; k++) {
                double g = gate[k] * s;
                if (g <= 0 && !(md && (gate[k] > 0 || fz))) continue;
                cd l = L[k], r = R[k], vL, vR, sp, aL, aR, sh = 0;
                double p2, wd = 0, wc = 0;
                if (!decomp(k, kEnd, g, l, r, vL, vR, p2, sp, aL, aR, &wd, nullptr, &wc)) {
                    if (md == 2 || md == 5 || md == 6) L[k] = R[k] = 0;
                    continue;
                }
                double gp = 1, wf = 0, eg = hp > 0 ? earG(vL, vR, hp) : 0.0;
                cd sf = eg > 0 ? eg * centerEst(k, kEnd, l, r, &gp, &wf) : cd(0);
                cd e = gp * sf;  // 貼耳的那一份（直接給兩耳）
                // 不進房間的那一份：rx＝1 認出來的人聲（這一瞬間沒送進耳朵的也不進）；rx＝2 有人聲的格照人聲佔的比例
                // 把整格的中擋在房間外（人聲沒被分乾淨的那一點也不會帶著房間聲拖在後面；沒有人聲的格吉他的房間聲不動）
                int rxm = rx.load();
                cd x = rxm == 2 ? eg * clampd(rxg.load() * wf, 0, 1) * 0.5 * (l + r) : rxm ? sf : e;
                if (md == 6) {  // 貼耳：正中間的聲音原封不動（只延遲 0° 的耳朵延遲，跟直達聲對齊）
                    L[k] = R[k] = e * std::polar(1.0, -omega[k] * t0);
                    continue;
                }
                cd cr = focusW(vL, vR, wd, wc) * (0.5 * (l + r) - x);  // 人聲集中的那一份（扣掉不進房間的之後剩下的中）
                double aL0 = std::abs(vL), aR0 = std::abs(vR);
                cd uL = (aL0 > 1e-12 ? vL / aL0 : cd(1, 0)) * std::sqrt(0.5 * (1 + p2));
                cd uR = (aR0 > 1e-12 ? vR / aR0 : cd(1, 0)) * std::sqrt(0.5 * (1 - p2));
                double tau = kItdMax * g * wd * p2 * itdw[k];           // 偏左 → 右耳晚到（只在低頻）
                if (tau > 0) uR *= std::polar(1.0, -omega[k] * tau);
                else if (tau < 0) uL *= std::polar(1.0, omega[k] * tau);
                if (md == 5) {  // 人聲集中：正中間的聲音（兩邊一樣；乘 √2：兩顆喇叭各送一份 → 一路送兩份的量）
                    L[k] = R[k] = fo * nr * std::sqrt(2.0) * cr;
                    continue;
                }
                double ak = gate[k] > 0 ? am * wd : 0.0;  // 環繞：混在一起的格裡的「環境音」其實是別的樂器 → 留在前面
                if (md == 2) {
                    L[k] = std::sqrt(ak) * aL;
                    R[k] = std::sqrt(ak) * aR * decor[k];
                } else {
                    double fk = md == 1 ? std::sqrt(1 - ak) : fa;
                    L[k] = uL * sp + fk * aL;
                    R[k] = uR * sp + fk * aR;
                    if (md == 1 && (fo > 0 || hp > 0)) {  // 人聲集中、貼耳：正中間的聲音不從這一路送到反射（改走 mode 5、6）
                        cd cc = x + fo * cr;
                        L[k] -= cc;
                        R[k] -= cc;
                    }
                }
            }
        }
        if (md == 6 && voc.load() > 0) vocShape(K, voc.load());
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
        if (mode.load() == 3) {  // 動態處理：時間域，沒有延遲
            dyn.process(inputs, outputs, n);
            return;
        }
        if (!N) {
            for (int c = 0; c < 2; c++)
                if (outputs[c] != inputs[c]) std::memcpy(outputs[c], inputs[c], sizeof(float) * n);
            return;
        }
        bool aiOn = dlLen > 0, own = false, live = false;
        int64_t s0 = 0, s1 = 0, mask = aiCap - 1;
        if (aiOn && aiH) {
            own = aiH[2] == aiId;  // 有更新的外掛接手了 → 這個只用 DSP
            s1 = aiH[8];
            MemoryBarrier();
            s0 = aiH[7];
            live = own && (int64_t)GetTickCount64() - aiH[9] < 1500;
        }
        double fstep = 1.0 / (kAiFadeSec * fs);
        for (int i = 0; i < n; i++) {
            float x0 = inputs[0][i], x1 = inputs[1][i];  // 輸出可能跟輸入同一塊記憶體：先拿
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
            if (aiOn) {  // DSP 人聲晚 dly 秒；AI 寫好了就換成 AI 的
                float d0 = dlL[dlPos], d1 = dlR[dlPos];
                dlL[dlPos] = o[0], dlR[dlPos] = o[1];
                if (++dlPos >= dlLen) dlPos = 0;
                o[0] = d0, o[1] = d1;
                if (own) {
                    int64_t w = aiPos & mask, p = aiPos - aiDelay;
                    aiIn[2 * w] = x0, aiIn[2 * w + 1] = x1;
                    if (live && p >= s0 && p < s1 && p > s1 - aiCap) {
                        aiMix = std::min(1.0, aiMix + fstep);
                        int64_t r = p & mask;
                        o[0] = (float)(aiMix * aiOut[2 * r] + (1 - aiMix) * d0);
                        o[1] = (float)(aiMix * aiOut[2 * r + 1] + (1 - aiMix) * d1);
                    } else {
                        aiMix = 0;
                    }
                    aiPos++;
                }
            }
            outputs[0][i] = o[0];
            outputs[1][i] = o[1];
        }
        if (own) {
            MemoryBarrier();
            aiH[6] = aiPos;
        }
    }
};

// 參數 k（例如 "ai="）只在開頭或分號後才算（"ai=" 也可能出現在別的字裡）
static const char* findKey(const char* b, const char* k) {
    for (const char* q = std::strstr(b, k); q; q = std::strstr(q + 1, k))
        if (q == b || q[-1] == ';') return q + std::strlen(k);
    return nullptr;
}

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
        std::snprintf(s->chunk, sizeof s->chunk,
                      "strength=%.3f;mode=%d;amb=%.3f;focus=%.3f;width=%.3f;near=%.3f;ear=%.3f;harsh=%d;game=%d%s%s",
                      s->strength.load(), s->mode.load(), s->amb.load(), s->focus.load(), s->width.load(), s->nearg.load(),
                      s->ear.load(), s->dyn.harsh, s->dyn.game, s->path[0] ? ";table=" : "", s->path);
        *(void**)ptr = s->chunk;
        return (intptr_t)std::strlen(s->chunk);
    case effSetChunk: {
        char b[512] = {0};
        std::memcpy(b, ptr, (size_t)std::min<intptr_t>(value, 511));
        const char* p = std::strstr(b, "strength=");
        if (p) s->strength.store((float)std::min(kStrengthMax, std::max(0.0, std::atof(p + 9))));
        if ((p = std::strstr(b, "mode="))) s->mode.store(std::min(6, std::max(0, std::atoi(p + 5))));
        if ((p = std::strstr(b, "esm="))) s->esm.store((float)std::min(0.1, std::max(0.003, std::atof(p + 4))));
        if ((p = std::strstr(b, "post="))) s->post.store((float)std::min(2.0, std::max(0.0, std::atof(p + 5))));
        if ((p = std::strstr(b, "rx="))) s->rx.store(std::min(2, std::max(0, std::atoi(p + 3))));
        if ((p = std::strstr(b, "rxg="))) s->rxg.store((float)std::min(4.0, std::max(0.5, std::atof(p + 4))));
        if ((p = std::strstr(b, "voc="))) s->voc.store((float)std::min(1.0, std::max(0.0, std::atof(p + 4))));
        if ((p = std::strstr(b, "vph="))) s->vph.store((float)std::min(1.0, std::max(0.0, std::atof(p + 4))));
        if ((p = std::strstr(b, "vwh="))) s->vwh.store((float)std::min(1500.0, std::max(50.0, std::atof(p + 4))));
        if ((p = std::strstr(b, "vlo="))) s->vlo.store((float)std::min(400.0, std::max(40.0, std::atof(p + 4))));
        if ((p = std::strstr(b, "vhi="))) s->vhi.store((float)std::min(16000.0, std::max(3000.0, std::atof(p + 4))));
        if ((p = std::strstr(b, "vnh="))) s->vnh.store(std::min(kVocNhMax, std::max(1, std::atoi(p + 4))));
        for (const char* q = std::strstr(b, "ear="); q; q = std::strstr(q + 1, "ear="))  // 要在開頭或分號後（near= 裡也有）
            if (q == b || q[-1] == ';') {
                s->ear.store((float)std::min(1.0, std::max(0.0, std::atof(q + 4))));
                break;
            }
        if ((p = std::strstr(b, "amb="))) s->amb.store((float)std::min(1.0, std::max(0.0, std::atof(p + 4))));
        if ((p = std::strstr(b, "focus="))) s->focus.store((float)std::min(1.0, std::max(0.0, std::atof(p + 6))));
        if ((p = std::strstr(b, "width="))) s->width.store((float)std::min(1.5, std::max(0.5, std::atof(p + 6))));
        if ((p = std::strstr(b, "near="))) s->nearg.store((float)std::min(1.0, std::max(0.0, std::atof(p + 5))));
        if ((p = std::strstr(b, "harsh="))) s->dyn.harsh = std::min(3, std::max(0, std::atoi(p + 6)));
        if ((p = std::strstr(b, "game="))) s->dyn.game = std::atoi(p + 5) ? 1 : 0;
        if ((p = std::strstr(b, "table="))) {  // 路徑到字串結尾（或下一個分號）
            size_t n = std::strcspn(p + 6, ";");
            n = std::min(n, sizeof s->path - 1);
            std::memcpy(s->path, p + 6, n);
            s->path[n] = 0;
            s->loadTable();
        }
        if ((p = findKey(b, "ai="))) s->ai.store((float)std::min(1.0, std::max(0.0, std::atof(p))));
        if ((p = findKey(b, "dly="))) s->dly.store((float)std::min(5.0, std::max(0.0, std::atof(p))));
        if ((p = findKey(b, "ailoc="))) s->ailoc.store(std::atoi(p) != 0);
        s->fx.initialDelay = s->mode.load() == 3 ? s->dyn.D : s->N - 1;
        if (s->fs > 0) s->aiSetup();
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
