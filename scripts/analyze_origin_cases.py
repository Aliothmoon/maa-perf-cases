#!/usr/bin/env python3
"""
Analyze preproc_and_match origin-case dumps.

Default input:
  src/Benchmark/OriginCases/maa_bench

Each case directory is expected to contain the dump format written by the
commented benchmark block in src/MaaCore/Vision/Matcher.cpp:
  params.json
  image.png
  <index>_<template-name>.png
  <index>_matched.f32
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parent / "OriginCases" / "maa_bench"


@dataclass(frozen=True)
class TemplateCase:
    case_id: str
    index: int
    image_size: tuple[int, int]
    template_name: str
    method: str
    threshold: float | None
    template_size: tuple[int, int] | None
    matched_size: tuple[int, int] | None
    max_val: float | None
    max_loc: tuple[int, int] | None
    has_mask: bool
    mask_signature: str
    mask_src: bool
    mask_close: bool
    has_color_scales: bool
    color_signature: str
    color_close: bool
    pure_color: bool
    template_count: int


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            header = f.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def matched_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            header = f.read(8)
    except OSError:
        return None
    if len(header) != 8:
        return None
    rows, cols = struct.unpack("<ii", header)
    if rows <= 0 or cols <= 0:
        return None
    return int(cols), int(rows)


def compact_range_signature(ranges: list[dict[str, Any]]) -> str:
    if not ranges:
        return "none"
    parts: list[str] = []
    for item in ranges:
        kind = item.get("type", "?")
        lo = item.get("lower")
        hi = item.get("upper")
        if isinstance(lo, list) or isinstance(hi, list):
            parts.append(f"{kind}:{lo}->{hi}")
        else:
            parts.append(f"{kind}:{lo}-{hi}")
    return ";".join(parts)


def load_case(case_dir: Path) -> list[TemplateCase]:
    params_path = case_dir / "params.json"
    try:
        meta = json.loads(params_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"failed to read {params_path}: {exc}") from exc

    image_size_raw = meta.get("image_size", [0, 0])
    image_size = (int(image_size_raw[0]), int(image_size_raw[1]))
    templ_names = list(meta.get("templ_names", []))
    methods = list(meta.get("methods", []))
    thresholds = list(meta.get("templ_thres", []))
    expected = list(meta.get("expected", []))
    mask_ranges = list(meta.get("mask_ranges", []))
    color_scales = list(meta.get("color_scales", []))
    mask_signature = compact_range_signature(mask_ranges)
    color_signature = compact_range_signature(color_scales)
    template_pngs: dict[int, Path] = {}
    for png in case_dir.glob("*.png"):
        match = re.match(r"(\d+)_", png.name)
        if match:
            template_pngs[int(match.group(1))] = png

    rows: list[TemplateCase] = []
    for i, templ_name in enumerate(templ_names):
        expected_item = expected[i] if i < len(expected) else {}
        max_loc_raw = expected_item.get("max_loc")
        max_loc = None
        if isinstance(max_loc_raw, list) and len(max_loc_raw) == 2:
            max_loc = (int(max_loc_raw[0]), int(max_loc_raw[1]))

        templ_png = template_pngs.get(i)
        rows.append(
            TemplateCase(
                case_id=case_dir.name,
                index=i,
                image_size=image_size,
                template_name=str(templ_name),
                method=str(methods[i]) if i < len(methods) else "missing",
                threshold=float(thresholds[i]) if i < len(thresholds) else None,
                template_size=png_size(templ_png) if templ_png else None,
                matched_size=matched_size(case_dir / f"{i}_matched.f32"),
                max_val=float(expected_item["max_val"]) if "max_val" in expected_item else None,
                max_loc=max_loc,
                has_mask=bool(mask_ranges),
                mask_signature=mask_signature,
                mask_src=bool(meta.get("mask_src", False)),
                mask_close=bool(meta.get("mask_close", False)),
                has_color_scales=bool(color_scales),
                color_signature=color_signature,
                color_close=bool(meta.get("color_close", True)),
                pure_color=bool(meta.get("pure_color", False)),
                template_count=len(templ_names),
            )
        )
    return rows


def scene_name(template_name: str) -> str:
    name = Path(template_name).name.lower()
    rules = [
        ("Infrast/base", ["infrast", "bskill", "facility", "manufacturing", "trading", "power", "dorm", "hire", "meeting", "office", "smiley"]),
        ("Battle/combat", ["battle", "skillready", "kills", "cost", "deploy", "retreat", "speed"]),
        ("Roguelike", ["roguelike", "is_", "is-", "recruitinvest"]),
        ("Recruit", ["recruit", "tag_", "refresh"]),
        ("Shop/mall", ["shop", "mall", "credit"]),
        ("Stage/navigation", ["stage", "terminal", "start", "sanity", "operation", "fight", "mission"]),
        ("Award/mail", ["award", "mail", "daily", "weekly", "missioncompleted"]),
        ("UI/common", ["close", "return", "confirm", "cancel", "setting", "theme", "back", "home"]),
    ]
    for scene, needles in rules:
        if any(needle in name for needle in needles):
            return scene
    return "Other"


def family_name(template_name: str) -> str:
    stem = Path(template_name).name
    stem = re.sub(r"\.png$", "", stem, flags=re.IGNORECASE)
    stem = stem.split("@", 1)[0]
    stem = re.split(r"[-_&.]", stem, 1)[0]
    return stem or "<empty>"


def input_class(row: TemplateCase) -> str:
    mask = "mask" if row.has_mask else "no-mask"
    color = "color" if row.has_color_scales else "no-color"
    pure = "pure" if row.pure_color else "mixed"
    multi = "multi" if row.template_count > 1 else "single"
    return f"{row.method}/{mask}/{color}/{pure}/{multi}"


def bucket_area(size: tuple[int, int] | None) -> str:
    if not size:
        return "unknown"
    area = size[0] * size[1]
    buckets = [
        (10_000, "<10k"),
        (50_000, "10k-50k"),
        (100_000, "50k-100k"),
        (250_000, "100k-250k"),
        (500_000, "250k-500k"),
        (1_000_000, "500k-1M"),
    ]
    for upper, label in buckets:
        if area < upper:
            return label
    return ">=1M"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * p / 100)
    return ordered[idx]


def print_counter(title: str, counter: Counter[str], total: int, top: int) -> None:
    print(f"\n=== {title} ===")
    for key, count in counter.most_common(top):
        pct = count * 100.0 / total if total else 0.0
        print(f"{count:7d} {pct:6.2f}%  {key}")


def print_size_stats(title: str, sizes: list[tuple[int, int]]) -> None:
    areas = [w * h for w, h in sizes]
    print(f"\n=== {title} ===")
    if not areas:
        print("no data")
        return
    print(f"count={len(areas)}")
    print(
        "area: "
        f"min={min(areas)} "
        f"p50={int(percentile(areas, 50))} "
        f"p90={int(percentile(areas, 90))} "
        f"p95={int(percentile(areas, 95))} "
        f"max={max(areas)}"
    )


def collect(root: Path) -> tuple[list[TemplateCase], list[Path]]:
    rows: list[TemplateCase] = []
    bad: list[Path] = []
    for params_path in sorted(root.glob("*/params.json"), key=lambda p: int(p.parent.name) if p.parent.name.isdigit() else p.parent.name):
        try:
            rows.extend(load_case(params_path.parent))
        except RuntimeError:
            bad.append(params_path.parent)
    return rows, bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT, help="maa_bench dump directory")
    parser.add_argument("--top", type=int, default=25, help="rows to print in top-N sections")
    args = parser.parse_args()

    rows, bad = collect(args.root)
    cases = {row.case_id for row in rows}
    total = len(rows)

    print(f"root: {args.root}")
    print(f"case dirs: {len(cases)}")
    print(f"template entries: {total}")
    if bad:
        print(f"bad dirs: {len(bad)}")
    if not rows:
        return 1

    sample_level = {}
    for row in rows:
        sample_level.setdefault(row.case_id, row)

    print_counter("Input Classes", Counter(input_class(r) for r in rows), total, args.top)
    print_counter("Methods", Counter(r.method for r in rows), total, args.top)
    print_counter("Mask Signatures", Counter(r.mask_signature for r in rows), total, args.top)
    print_counter("Color Signatures", Counter(r.color_signature for r in rows), total, args.top)
    print_counter("Template Count Per Call", Counter(str(r.template_count) for r in sample_level.values()), len(sample_level), args.top)

    print_counter("Image Area Buckets", Counter(bucket_area(r.image_size) for r in sample_level.values()), len(sample_level), args.top)
    print_counter("Template Area Buckets", Counter(bucket_area(r.template_size) for r in rows), total, args.top)
    print_size_stats("Image Size Stats", [r.image_size for r in sample_level.values()])
    print_size_stats("Template Size Stats", [r.template_size for r in rows if r.template_size])

    print_counter("Scene Heuristic", Counter(scene_name(r.template_name) for r in rows), total, args.top)
    print_counter("Template Families", Counter(family_name(r.template_name) for r in rows), total, args.top)
    print_counter("Top Templates", Counter(r.template_name for r in rows), total, args.top)

    positive = [r for r in rows if r.max_val is not None and r.threshold is not None and r.max_val >= r.threshold]
    print(f"\npositive expected hits: {len(positive)} / {total} ({len(positive) * 100.0 / total:.2f}%)")

    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[scene_name(row.template_name)][input_class(row)] += 1
    print("\n=== Scene x Input Class Top Mix ===")
    for scene, counter in sorted(grouped.items(), key=lambda item: sum(item[1].values()), reverse=True):
        count = sum(counter.values())
        top_mix = ", ".join(f"{k}={v}" for k, v in counter.most_common(3))
        print(f"{count:7d} {count * 100.0 / total:6.2f}%  {scene}: {top_mix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
