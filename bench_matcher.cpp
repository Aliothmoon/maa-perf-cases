#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>
#include <set>
#include <string>
#include <vector>

#include <meojson/json.hpp>

#include "Common/AsstTypes.h"
#include "MaaUtils/ImageIo.h"
#include "MaaUtils/NoWarningCV.hpp"
#include "Vision/Config/MatcherConfig.h"
#include "Vision/Matcher.h"

namespace fs = std::filesystem;
using Clock  = std::chrono::steady_clock;
using Us     = std::chrono::microseconds;

// ---- 工具 ----------------------------------------------------------------

struct Stats
{
    long long min_us, p50_us, p95_us, avg_us, max_us;
    int       count;
};

Stats measure(int warmup, int iters, auto&& fn)
{
    for (int i = 0; i < warmup; ++i) fn();

    std::vector<long long> ts(iters);
    for (int i = 0; i < iters; ++i) {
        auto t0 = Clock::now();
        fn();
        ts[i] = std::chrono::duration_cast<Us>(Clock::now() - t0).count();
    }
    std::sort(ts.begin(), ts.end());
    long long sum = std::accumulate(ts.begin(), ts.end(), 0LL);
    return {
        ts.front(),
        ts[iters / 2],
        ts[static_cast<int>(iters * 0.95)],
        sum / iters,
        ts.back(),
        iters,
    };
}

void print_stats(const char* label, const Stats& s)
{
    std::printf("%-48s  min=%5lld  p50=%5lld  p95=%5lld  avg=%5lld  max=%5lld  (us, n=%d)\n",
                label, s.min_us, s.p50_us, s.p95_us, s.avg_us, s.max_us, s.count);
}

// ---- 从 dump 重建 MatcherConfig::Params ----------------------------------

// 把 json Range 数组反序列化为 MatchTaskInfo::Ranges
static asst::MatchTaskInfo::Ranges parse_ranges(const json::array& arr)
{
    asst::MatchTaskInfo::Ranges ranges;
    for (const auto& item : arr) {
        const std::string type = item.get("type", std::string("gray"));
        if (type == "gray") {
            ranges.emplace_back(asst::MatchTaskInfo::GrayRange {
                item.get("lower", 0),
                item.get("upper", 255),
            });
        }
        else { // "color"
            const auto& lo = item.at("lower").as_array();
            const auto& hi = item.at("upper").as_array();
            ranges.emplace_back(asst::MatchTaskInfo::ColorRange {
                std::array<int, 3> { lo[0].as_integer(), lo[1].as_integer(), lo[2].as_integer() },
                std::array<int, 3> { hi[0].as_integer(), hi[1].as_integer(), hi[2].as_integer() },
            });
        }
    }
    return ranges;
}

struct Sample
{
    std::string              label;         // 目录名，方便识别
    cv::Mat                  image;         // roi 输入图
    asst::MatcherConfig::Params params;     // 完整参数

    // 期望结果（用于正确性校验）
    struct Expected
    {
        std::string templ_name;
        double      max_val  = 0.0;
        int         max_loc_x = 0, max_loc_y = 0;
        cv::Mat     matched;    // float32 矩阵，可选（文件较大时可跳过）
    };
    std::vector<Expected> expected;
};

// 读取 .f32 文件 → float32 cv::Mat
static cv::Mat load_f32(const fs::path& path)
{
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs) return {};
    int32_t rows = 0, cols = 0;
    ifs.read(reinterpret_cast<char*>(&rows), 4);
    ifs.read(reinterpret_cast<char*>(&cols), 4);
    if (rows <= 0 || cols <= 0) return {};
    cv::Mat mat(rows, cols, CV_32F);
    ifs.read(reinterpret_cast<char*>(mat.ptr<float>(0)),
             static_cast<std::streamsize>(rows) * cols * sizeof(float));
    return mat;
}

static std::optional<Sample> load_sample(const fs::path& dir)
{
    // --- params.json ---
    std::ifstream pf(dir / "params.json");
    if (!pf) {
        std::cerr << "[warn] no params.json in " << dir << "\n";
        return std::nullopt;
    }
    std::string json_str((std::istreambuf_iterator<char>(pf)), {});
    auto jopt = json::parse(json_str);
    if (!jopt) {
        std::cerr << "[warn] failed to parse params.json in " << dir << "\n";
        return std::nullopt;
    }
    const auto& j = *jopt;

    // --- image ---
    cv::Mat image = MAA_NS::imread(dir / "image.png");
    if (image.empty()) {
        std::cerr << "[warn] image.png missing in " << dir << "\n";
        return std::nullopt;
    }

    // --- 模板图 ---
    // 文件名格式：{index}_{templ_name}.png
    std::vector<std::pair<int, cv::Mat>> templ_files; // (index, mat)
    for (const auto& entry : fs::directory_iterator(dir)) {
        const std::string fname = entry.path().filename().string();
        if (fname == "image.png" || fname == "params.json") continue;
        if (entry.path().extension() != ".png") continue;
        // 取前缀数字
        size_t sep = fname.find('_');
        if (sep == std::string::npos) continue;
        int idx = std::stoi(fname.substr(0, sep));
        cv::Mat t = MAA_NS::imread(entry.path());
        if (!t.empty()) templ_files.emplace_back(idx, std::move(t));
    }
    std::sort(templ_files.begin(), templ_files.end(),
              [](const auto& a, const auto& b){ return a.first < b.first; });

    if (templ_files.empty()) {
        std::cerr << "[warn] no template PNGs in " << dir << "\n";
        return std::nullopt;
    }

    // --- 重建 Params ---
    asst::MatcherConfig::Params params;

    for (auto& [idx, mat] : templ_files)
        params.templs.emplace_back(std::move(mat));

    const auto& methods_j = j.at("methods").as_array();
    for (const auto& m : methods_j)
        params.methods.push_back(asst::get_match_method(m.as_string()));

    const auto& thres_j = j.at("templ_thres").as_array();
    for (const auto& t : thres_j)
        params.templ_thres.push_back(t.as_double());

    if (j.contains("mask_ranges"))
        params.mask_ranges = parse_ranges(j.at("mask_ranges").as_array());
    params.mask_src   = j.get("mask_src",   false);
    params.mask_close = j.get("mask_close", false);

    if (j.contains("color_scales"))
        params.color_scales = parse_ranges(j.at("color_scales").as_array());
    params.color_close = j.get("color_close", true);
    params.pure_color  = j.get("pure_color",  false);

    // --- 期望结果 ---
    std::vector<Sample::Expected> expected;
    if (j.contains("expected")) {
        const auto& exp_arr = j.at("expected").as_array();
        for (size_t i = 0; i < exp_arr.size(); ++i) {
            const auto& e = exp_arr[i];
            Sample::Expected ex;
            ex.templ_name = e.get("templ", std::string());
            ex.max_val    = e.get("max_val", 0.0);
            const auto& loc = e.at("max_loc").as_array();
            ex.max_loc_x  = loc[0].as_integer();
            ex.max_loc_y  = loc[1].as_integer();
            // .f32 可选
            auto f32_path = dir / (std::to_string(i) + "_matched.f32");
            if (fs::exists(f32_path))
                ex.matched = load_f32(f32_path);
            expected.push_back(std::move(ex));
        }
    }

    return Sample {
        dir.filename().string(),
        std::move(image),
        std::move(params),
        std::move(expected),
    };
}

// ---- 正确性校验 ----------------------------------------------------------

static bool verify(const Sample& sample, const std::vector<asst::Matcher::RawResult>& results,
                   double match_threshold = 0.75, double val_tol = 2e-3)
{
    bool ok = true;
    for (size_t i = 0; i < sample.expected.size() && i < results.size(); ++i) {
        const auto& ex = sample.expected[i];
        const auto& r  = results[i];

        const bool ex_hit = (ex.max_val >= match_threshold);

        if (r.matched.empty()) {
            if (ex_hit) {
                std::printf("  [FAIL] templ %zu '%s': expected hit (%.4f) but matched is empty\n",
                            i, ex.templ_name.c_str(), ex.max_val);
                ok = false;
            }
            continue;
        }

        double max_val = 0.0;
        cv::Point max_loc;
        cv::Mat valid_mask;
        cv::inRange(r.matched, 0.0f, 1.0f + 1e-5f, valid_mask);
        cv::minMaxLoc(r.matched, nullptr, &max_val, nullptr, &max_loc, valid_mask);

        const bool got_hit = (max_val >= match_threshold);

        if (ex_hit != got_hit) {
            // 命中/未命中判断不一致：硬 FAIL
            std::printf("  [FAIL] templ %zu '%s': expected %s (%.4f) got %s (%.4f)\n",
                        i, ex.templ_name.c_str(),
                        ex_hit ? "HIT" : "MISS", ex.max_val,
                        got_hit ? "HIT" : "MISS", max_val);
            ok = false;
            continue;
        }

        if (!ex_hit) continue; // 双方都是未命中，不再校验精度

        // 双方都命中：校验 val 精度和 loc
        const double val_diff = std::abs(max_val - ex.max_val);
        const bool   loc_match = (max_loc.x == ex.max_loc_x && max_loc.y == ex.max_loc_y);

        if (val_diff > val_tol) {
            std::printf("  [FAIL] templ %zu '%s': val %.4f→%.4f (diff %.4f > tol) loc=(%d,%d)→(%d,%d)\n",
                        i, ex.templ_name.c_str(),
                        ex.max_val, max_val, val_diff,
                        ex.max_loc_x, ex.max_loc_y, max_loc.x, max_loc.y);
            ok = false;
        }
        else if (!loc_match) {
            std::printf("  [WARN] templ %zu '%s': val ok (%.4f≈%.4f) loc differs (%d,%d)→(%d,%d)\n",
                        i, ex.templ_name.c_str(),
                        ex.max_val, max_val,
                        ex.max_loc_x, ex.max_loc_y, max_loc.x, max_loc.y);
        }
    }
    return ok;
}

// ---- main ----------------------------------------------------------------

int main(int argc, char** argv)
{
    if (argc < 2) {
        std::cerr << "Usage: bench_matcher <dump_dir> [iterations=200] [case_ids]\n"
                  << "  dump_dir:   directory containing numbered sample subdirs (e.g. bench_samples/)\n"
                  << "  case_ids:   comma-separated sample IDs to run (e.g. \"155,22,170\").\n"
                  << "              omit or pass \"*\" / \"all\" to run every sample.\n";
        return 1;
    }

    const fs::path dump_dir(argv[1]);
    const int iters  = argc >= 3 ? std::stoi(argv[2]) : 200;
    const int warmup = std::max(5, iters / 20);

    std::set<std::string> case_filter;
    if (argc >= 4) {
        std::string spec = argv[3];
        if (spec != "*" && spec != "all" && !spec.empty()) {
            size_t pos = 0;
            while (pos < spec.size()) {
                size_t comma = spec.find(',', pos);
                size_t end   = (comma == std::string::npos) ? spec.size() : comma;
                // trim spaces
                size_t a = pos, b = end;
                while (a < b && std::isspace(static_cast<unsigned char>(spec[a]))) ++a;
                while (b > a && std::isspace(static_cast<unsigned char>(spec[b - 1]))) --b;
                if (b > a) case_filter.insert(spec.substr(a, b - a));
                pos = (comma == std::string::npos) ? spec.size() : comma + 1;
            }
        }
    }

    if (!fs::is_directory(dump_dir)) {
        std::cerr << "not a directory: " << dump_dir << "\n";
        return 1;
    }

    // 收集所有样本子目录（名称为数字）
    std::vector<fs::path> sample_dirs;
    for (const auto& entry : fs::directory_iterator(dump_dir)) {
        if (!entry.is_directory()) continue;
        if (!case_filter.empty() && !case_filter.count(entry.path().filename().string())) continue;
        sample_dirs.push_back(entry.path());
    }
    std::sort(sample_dirs.begin(), sample_dirs.end());

    if (sample_dirs.empty()) {
        if (!case_filter.empty()) {
            std::cerr << "no sample directories matched filter (" << case_filter.size()
                      << " ids) in " << dump_dir << "\n";
        } else {
            std::cerr << "no sample directories in " << dump_dir << "\n";
        }
        return 1;
    }

    if (!case_filter.empty()) {
        std::printf("loaded dump dir: %s  (%zu/%zu samples after filter)  iters=%d\n\n",
                    dump_dir.string().c_str(), sample_dirs.size(), case_filter.size(), iters);
    } else {
        std::printf("loaded dump dir: %s  (%zu samples)  iters=%d\n\n",
                    dump_dir.string().c_str(), sample_dirs.size(), iters);
    }
    std::printf("%-48s  %5s  %5s  %5s  %5s  %5s  (us)\n",
                "sample", "min", "p50", "p95", "avg", "max");
    std::printf("%s\n", std::string(100, '-').c_str());

    int fail_count = 0;

    for (const auto& dir : sample_dirs) {
        auto sample_opt = load_sample(dir);
        if (!sample_opt) continue;
        auto& sample = *sample_opt;

        // --- timing ---
        std::vector<asst::Matcher::RawResult> last_result;
        auto s = measure(warmup, iters, [&] {
            last_result = asst::Matcher::preproc_and_match(sample.image, sample.params);
        });
        print_stats(sample.label.c_str(), s);

        // --- correctness ---
        if (!sample.expected.empty()) {
            if (!verify(sample, last_result)) ++fail_count;
        }
    }

    std::printf("\n%s\n", std::string(100, '-').c_str());
    if (fail_count > 0)
        std::printf("[RESULT] %d sample(s) FAILED correctness check\n", fail_count);
    else
        std::printf("[RESULT] all correctness checks passed\n");

    return fail_count > 0 ? 1 : 0;
}
