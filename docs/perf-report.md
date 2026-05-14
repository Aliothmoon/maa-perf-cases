## 摘要

| 平台 | 集合 | mean | p99 |
|---|---|---|---|
| Windows MSVC x64 | coverage (n=803) | 10.5ms → **6.4ms** (1.64x) | 141ms → **65ms** (2.16x) |
| Windows MSVC x64 | perf (n=1402) | 854us → **267us** (3.20x) | 9.7ms → **5.3ms** (1.84x) |
| Android arm64 NEON | coverage (n=803) | 125ms → **78ms** (1.60x) | 1735ms → **725ms** (2.39x) |
| Android arm64 NEON | perf (n=1402) | 6.4ms → **2.9ms** (2.20x) | 120ms → **71ms** (1.68x) |

- Windows perf p50：**10.0x**，Android perf p50：**11.7x**

## 优化点

| 编号 | 改动 | 解决的退化类型 |
|---|---|---|
| 1 | 缓存检查时尽量无锁处理 | 小 case 固定 mutex 开销（cat 3）|
| 2 | 中等 result + 中等 K 判定回退 OpenCV | GameStart 类稀疏适用区 |
| 3 | `K*result < 25M` 判定回退 OpenCV | SmileyOnWork 类长条 FFT |
| 4 | 极小 result 早返回限定 `K<2000` | InfrastTraining 类高 K 小 result |
| 5 | 利用卷积线性把 Σ_c (M⋆I_c²) 合成 M⋆(Σ_c I_c²) | 真 FFT 路径 -22% (15→11 次变换) |


## 图表

### 分位延迟（log 纵轴）

![percentiles](figures/percentiles.png)

### 延迟 CDF

![cdf](figures/cdf.png)

### 单 case 加速分布（log 横轴）

![speedup_hist](figures/speedup_hist.png)

### 散点对比（log-log，绿=加速、红=退化、灰=持平）

![scatter](figures/scatter.png)

## 详细数据

Windows = min-of-2 runs，Android = single run。

| 平台 | 集合 | 指标 | baseline | optimized | speedup |
|---|---|---|---:|---:|---:|
| windows | coverage | p50 | 2,337us | 1,768us | **1.32x** |
| | | p95 | 35,241us | 31,660us | 1.11x |
| | | p99 | 141,132us | 65,457us | **2.16x** |
| | | mean | 10,465us | 6,363us | **1.64x** |
| windows | perf | p50 | 723us | **72us** | **10.04x** |
| | | p95 | 813us | 278us | 2.92x |
| | | p99 | 9,714us | 5,267us | 1.84x |
| | | mean | 854us | 267us | **3.20x** |
| android | coverage | p50 | 30,016us | 24,956us | 1.20x |
| | | p95 | 442,340us | 370,143us | 1.20x |
| | | p99 | 1,734,833us | 725,098us | **2.39x** |
| | | mean | 125,176us | 78,061us | **1.60x** |
| android | perf | p50 | 4,219us | **361us** | **11.69x** |
| | | p95 | 5,071us | 4,272us | 1.19x |
| | | p99 | 119,905us | 71,468us | 1.68x |
| | | mean | 6,389us | 2,899us | **2.20x** |


## 流程

1. **基线测量** — `commit 5e78b23157` 之前的纯 OpenCV `cv::matchTemplate(..., mask)` 实现，分别在 Windows / Android 跑全量
2. **退化诊断** — 把 FFT/sparse 上线后的 latest 与 baseline 对比，按代码路径分类回归 case（cat 1-4）
3. **反复调参** — 对每个 case 用 Python 算出 `(K, result, K*result, n_dy)`，按这些维度做 bucket 分析，统计退化/中性/加速分布
4. **逐步优化** — bench_matcher 支持指定 case 过滤，每一步只跑对应的回归子集（含正向 sanity case），避免噪声淹没改动
5. **全量回归** — Windows 串行跑 2 次取 min（噪声 10-15%）；Android K20 Pro 单次（噪声 <1%）
6. **正确性兜底** — `verify()` 用 `match_threshold=0.75` + `val_tol=2e-3`，跨 1 万次迭代正确性全过

## 测试集

| 集合 | 样本数 | 构造规则 |
|---|---:|---|
| coverage | 803 | 全部 `>=200ms` + 全部稀有 method (HSVCount/RGBCount) + 全部 multi-template + timing×scene 分层抽样 |
| perf | 1402 | 按生产 timing 分布加权采样，p50/p95  |

源：从 54973 个生产捕获 case 中抽样（`scripts/select_cases.py`）

## 残留与噪声

| 现象 | 说明 |
|---|---|
| Windows perf 少量回归 case | 全部 <1.33x，绝对延迟 <500us，落在测量噪声内 |
| Windows noise floor | 同代码两次 run 的 case-wise diff：coverage p50 = 9.5%、perf p50 = 13%，故采用 min-of-2 |
| Android noise floor | 同代码 3 次 run 的差异 <1%，单次结果即可信 |

## 测量环境

| 平台 | 设备 / 构建 |
|---|---|
| Windows MSVC x64 | RelWithDebInfo, MSVC 19.x |
| Android arm64-v8a | Redmi K20 Pro / Android 11, NDK r29 RelWithDebInfo Clang, OpenCV 4.x |

详细见 `RegressionCases/baseline/README.md`。
