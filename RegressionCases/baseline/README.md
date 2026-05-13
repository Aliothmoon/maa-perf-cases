# Baseline 数据

本目录记录 `Matcher::preproc_and_match` 优化前的基线结果，按平台拆分：

| 平台 | coverage | perf |
|---|---|---|
| Android arm64-v8a | `android/coverage.txt` | `android/perf.txt` |
| Windows x64 MSVC | `windows/coverage.txt` | `windows/perf.txt` |

`coverage` 用于覆盖更多输入形态和正确性回归，`perf` 按真实生产分布采样，用于观察稳定性能分布。每行格式：

```text
<sample_id>  min=<us>  p50=<us>  p95=<us>  avg=<us>  max=<us>  (us, n=<iters>)
```

## Baseline 来源

Android baseline 来自 `c6f930a60d` 之前的 `Matcher.cpp` 行为：带 mask 时直接走 `cv::matchTemplate`，未启用 `fast_masked_ccoeff_normed`，未启用 FFT cache。

Windows baseline 来自 `5e78b23157`，测试时只叠加了 bench 所需的临时构建补丁：启用 `BUILD_BENCHMARK`，并为 MSVC 链接导出 `Matcher::preproc_and_match`。这些补丁不改变 matcher 业务逻辑。

## 测量环境

### Android

| 项 | 值 |
|---|---|
| 设备 | Redmi K20 Pro |
| 系统 | Android 11 |
| ABI | arm64-v8a |
| NDK | r29.0.13599879 |
| 构建类型 | RelWithDebInfo |
| 编译器 | Clang (NDK 默认) |
| OpenCV | `src/MaaUtils/MaaDeps/runtime/maa-arm64-android/libopencv_world4.so` |
| 测试程序 | `src/Benchmark/bench_matcher.cpp` |
| 待测函数 | `Matcher::preproc_and_match` |
| 测试二进制 | `cmake-build-ndk/bin/bench_matcher` |
| 设备部署路径 | `/data/local/tmp/bench/` |
| 样本根目录 | `/data/local/tmp/RegressionCases/` |

### Windows

| 项 | 值 |
|---|---|
| 系统 | Windows x64 |
| 构建目录 | `cmake-build-debug` |
| 构建类型 | RelWithDebInfo |
| 编译器 | MSVC |
| 测试程序 | `src/Benchmark/bench_matcher.cpp` |
| 待测函数 | `Matcher::preproc_and_match` |
| 测试二进制 | `cmake-build-debug/bin/RelWithDebInfo/bench_matcher.exe` |
| 样本根目录 | `src/Benchmark/RegressionCases/` |

计时方法均为 `std::chrono::steady_clock`，warmup `max(5, iters / 20)` 次后取 `iters` 次平均/p50/p95。

## Baseline 指标

### Android coverage（n=803，1 次迭代）

| 指标 | 值 |
|---|---:|
| min | 1.18 ms |
| p50 | 30.02 ms |
| p75 | 119.32 ms |
| p90 | 213.99 ms |
| p95 | 442.34 ms |
| p99 | 1734.83 ms |
| max | 2344.02 ms |
| mean | 125.18 ms |

### Android perf（n=1402，20 次迭代）

| 指标 | 值 |
|---|---:|
| min | 1.84 ms |
| p50 | 4.22 ms |
| p75 | 4.25 ms |
| p90 | 4.80 ms |
| p95 | 5.07 ms |
| p99 | 119.91 ms |
| max | 154.91 ms |
| mean | 6.39 ms |

### Windows coverage（n=803，1 次迭代）

| 指标 | 值 |
|---|---:|
| min | 0.10 ms |
| p50 | 2.34 ms |
| p75 | 8.91 ms |
| p90 | 16.39 ms |
| p95 | 35.24 ms |
| p99 | 141.13 ms |
| max | 256.22 ms |
| mean | 10.47 ms |

### Windows perf（n=1402，20 次迭代）

| 指标 | 值 |
|---|---:|
| min | 0.14 ms |
| p50 | 0.72 ms |
| p75 | 0.75 ms |
| p90 | 0.78 ms |
| p95 | 0.81 ms |
| p99 | 9.71 ms |
| max | 16.45 ms |
| mean | 0.85 ms |

## 当前优化效果

下表的 speedup = baseline / optimized，数值大于 1 表示优化后更快。Android optimized 来源为 `../result_perf_final.txt`、`../result_coverage_final.txt`；Windows optimized 来源为 `../result_perf_windows_current.txt`、`../result_coverage_windows_current.txt`。

| 平台 | 集合 | p50 | p95 | p99 | mean | 结论 |
|---|---|---:|---:|---:|---:|---|
| Android | perf | 13.39x | 1.41x | 3.02x | 3.82x | 主生产分布显著变快，p95 收益较小但仍为正 |
| Android | coverage | 1.11x | 1.15x | 1.76x | 1.70x | 大覆盖集整体变快，长尾改善明显 |
| Windows | perf | 9.77x | 2.58x | 0.57x | 2.10x | 常规样本显著变快，p99 局部退化 |
| Windows | coverage | 1.14x | 1.08x | 2.03x | 1.28x | 覆盖集整体小幅变快，长尾改善明显 |

## 重跑命令

### Android

```bash
adb push cmake-build-ndk/bin/bench_matcher /data/local/tmp/bench/
adb push cmake-build-ndk/bin/libMaaCore.so /data/local/tmp/bench/
adb push cmake-build-ndk/bin/libMaaUtils.so /data/local/tmp/bench/
adb push src/MaaUtils/MaaDeps/runtime/maa-arm64-android/*.so /data/local/tmp/bench/
adb shell chmod +x /data/local/tmp/bench/bench_matcher

adb shell "LD_LIBRARY_PATH=/data/local/tmp/bench \
  /data/local/tmp/bench/bench_matcher \
  /data/local/tmp/RegressionCases/coverage 1 \
  > /data/local/tmp/result_coverage.txt 2>&1"
adb pull /data/local/tmp/result_coverage.txt src/Benchmark/RegressionCases/baseline/android/coverage.txt

adb shell "LD_LIBRARY_PATH=/data/local/tmp/bench \
  /data/local/tmp/bench/bench_matcher \
  /data/local/tmp/RegressionCases/perf 20 \
  > /data/local/tmp/result_perf.txt 2>&1"
adb pull /data/local/tmp/result_perf.txt src/Benchmark/RegressionCases/baseline/android/perf.txt
```

### Windows

```powershell
.\cmake-build-debug\bin\RelWithDebInfo\bench_matcher.exe `
  .\src\Benchmark\RegressionCases\coverage 1 `
  > .\src\Benchmark\RegressionCases\baseline\windows\coverage.txt 2>&1

.\cmake-build-debug\bin\RelWithDebInfo\bench_matcher.exe `
  .\src\Benchmark\RegressionCases\perf 20 `
  > .\src\Benchmark\RegressionCases\baseline\windows\perf.txt 2>&1
```
