# maa-perf-cases

`MaaAssistantArknights` 中 `Matcher::preproc_and_match` 的性能回归用例集和基准工具。

用于：
- 对 `Matcher` / `MaskedCcoeffMatcher` 改动做覆盖回归 + 性能 A/B
- 跨平台（Windows MSVC / Android NDK）对比

> **优化结果** — [`docs/perf-report.md`](docs/perf-report.md)
> Windows perf p50 **8.6x**，Android perf p50 **16.0x**，Android 两个集合 **零回归**。

## 目录

```
.
├── CMakeLists.txt            # bench_matcher 的子项目 CMake，由根 CMake add_subdirectory 引入
├── bench_matcher.cpp         # 基准 + 正确性校验入口
├── RegressionCases/          # 测试用例数据
│   ├── baseline/             # 优化前基线测量结果
│   │   ├── README.md         # 测量环境 / baseline 来源 commit / 重跑命令
│   │   ├── android/{coverage,perf}.txt
│   │   └── windows/{coverage,perf}.txt
│   ├── coverage/             # 803 个覆盖型用例 (各种代码路径 + 长尾)
│   └── perf/                 # 1402 个性能型用例 (按真实生产分布采样)
├── scripts/
│   ├── analyze_bench.py
│   └── analyze_origin_cases.py
└── patches/
    └── 0001-enable-benchmark-subdir.patch   # 应用到 MAA 根 CMakeLists.txt
```

## 用法

### 1. 在 MaaAssistantArknights 仓库根目录应用 patch

```bash
cd /path/to/MaaAssistantArknights
git apply /path/to/maa-perf-cases/patches/0001-enable-benchmark-subdir.patch
```

效果：根 `CMakeLists.txt` 末尾追加

```cmake
option(BUILD_BENCHMARK "build matcher benchmark" ON)
if(BUILD_BENCHMARK)
    add_subdirectory(src/Benchmark)
endif()
```

### 2. 把本仓库内容铺到 `src/Benchmark/`

```bash
# 在 MaaAssistantArknights 仓库根目录下
mkdir -p src/Benchmark
cp <maa-perf-cases>/bench_matcher.cpp        src/Benchmark/
cp <maa-perf-cases>/CMakeLists.txt           src/Benchmark/
cp -r <maa-perf-cases>/RegressionCases       src/Benchmark/
```

`src/Benchmark` 被 MAA 根仓库 `.gitignore` 排除，不会脏 working tree。

### 3. 构建

Windows MSVC：

```powershell
cmake -B cmake-build-debug -A x64 -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build cmake-build-debug --target bench_matcher --config RelWithDebInfo
```

Android NDK arm64-v8a：

```bash
cmake -B cmake-build-ndk -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK/build/cmake/android.toolchain.cmake \
                         -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
                         -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build cmake-build-ndk --target bench_matcher
```

### 4. 跑 bench

```
bench_matcher <dump_dir> [iterations=200] [case_ids]
  dump_dir:  RegressionCases/coverage 或 RegressionCases/perf
  case_ids:  逗号分隔的样本 ID（如 "155,22,170"），"*" 或省略 = 全量
```

只跑指定 case 验证

```bash
bench_matcher RegressionCases/perf 50 "280,281,279,54911,54912"
```

跑全量做 p50/p95/p99 对比：

```bash
bench_matcher RegressionCases/coverage 20 > result_coverage.txt
bench_matcher RegressionCases/perf 20     > result_perf.txt
```

Android 例：

```bash
adb push cmake-build-ndk/bin/bench_matcher /data/local/tmp/bench/
adb push cmake-build-ndk/bin/libMaaCore.so /data/local/tmp/bench/
adb push cmake-build-ndk/bin/libMaaUtils.so /data/local/tmp/bench/
adb push <opencv .so> /data/local/tmp/bench/
adb shell chmod +x /data/local/tmp/bench/bench_matcher

# 推 RegressionCases（首次，~216MB）
adb push RegressionCases /data/local/tmp/

adb shell "LD_LIBRARY_PATH=/data/local/tmp/bench \
  /data/local/tmp/bench/bench_matcher \
  /data/local/tmp/RegressionCases/perf 20 \
  > /data/local/tmp/result_perf.txt 2>&1"
adb pull /data/local/tmp/result_perf.txt .
```

## 用例集构造

`coverage`（803 个）和 `perf`（1402 个）是从 54973 个生产捕获 case 中按以下规则抽取的，详见 `scripts/select_cases.py`（在 MAA 仓库的 `src/Benchmark/` 下）：

- `coverage`：尽可能多覆盖代码路径
  - 所有 `>=200ms` 极端慢 case
  - 所有 `HSVCount` / `RGBCount` 稀有方法
  - 所有 multi-template
  - 各 timing bucket × scene 分层抽样
- `perf`：从实际运行的dump数据里取的，用于稳定的 p50/p95 对比

## Baseline 与重跑

`baseline/{android,windows}/{coverage,perf}.txt` 是优化前的固定基线。Baseline 来源 commit 和测量环境（设备、NDK 版本、构建类型等）见 `baseline/README.md`。

每行格式（bench_matcher 直接输出）：
```
<sample_id>  min=<us>  p50=<us>  p95=<us>  avg=<us>  max=<us>  (us, n=<iters>)
```

## 校验逻辑

`bench_matcher.cpp::verify()` 对每个 case 用 `match_threshold=0.75` + `val_tol=2e-3` 判定：
- 都未命中 (`< 0.75`)：忽略
- 命中/未命中不一致：FAIL
- 都命中：检查 max_val 差与 max_loc 是否一致

也就是说 score 太低本就是匹配失败状态，优化后小幅 score 漂移不会被误报。
