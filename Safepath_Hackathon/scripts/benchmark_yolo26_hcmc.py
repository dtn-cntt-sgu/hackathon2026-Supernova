#!/usr/bin/env python3
"""
Benchmark script: Evaluates YOLO26n motorcycle and vehicle detection
across authentic HCMC traffic camera frames (306x236) in storage/cams/.
Compares single-frame inference vs Original-frame multiscale inference + Class-Aware NMS.
"""

import glob
import os
import time
import numpy as np

from backend.app.services.vision import (
    VehicleDetector,
    preprocess_camera_image,
)

def run_benchmark():
    raw_frames = [
        p for p in sorted(glob.glob("storage/cams/*.jpg"))
        if not p.endswith(("_analyzed.jpg", "_annotated.jpg", "_enhanced.jpg"))
    ]
    if not raw_frames:
        print("No raw camera frames found in storage/cams/")
        return

    benchmark_subset = raw_frames[:25]
    print(f"Running benchmark across {len(benchmark_subset)} authentic HCMC camera frames...\n")

    detector = VehicleDetector()
    assert detector.model_status == "VERIFIED_ONNX_INFERENCE", "Detector failed to initialize with YOLO26n"

    stats_single = {
        "motorcycles": 0,
        "cars": 0,
        "buses": 0,
        "trucks": 0,
        "total_vehicles": 0,
        "latencies": [],
    }

    stats_tiled = {
        "motorcycles": 0,
        "cars": 0,
        "buses": 0,
        "trucks": 0,
        "total_vehicles": 0,
        "latencies": [],
        "deltas": [],
    }

    print(f"{'Camera Frame':<40} | {'Base (M/C/Tot)':<15} | {'Original+Tile (M/C/Tot)':<20} | {'Delta':<6} | {'Latency':<10}")
    print("-" * 105)

    for frame_path in benchmark_subset:
        frame_name = os.path.basename(frame_path)
        prep = preprocess_camera_image(frame_path)

        # 1. Base Single Frame (No tiling, single branch)
        t0 = time.perf_counter()
        raw_candidates = detector._extract_frame_candidates(
            prep.original_image, prep.height, prep.width, min_conf=0.20
        )
        base_vehicles = detector._apply_class_aware_nms(raw_candidates, conf_threshold=0.25, motorcycle_conf=0.20)
        t_base_ms = (time.perf_counter() - t0) * 1000.0

        base_m = sum(1 for v in base_vehicles if v.cls_name == "motorcycle")
        base_c = sum(1 for v in base_vehicles if v.cls_name == "car")
        stats_single["motorcycles"] += base_m
        stats_single["cars"] += base_c
        stats_single["total_vehicles"] += len(base_vehicles)
        stats_single["latencies"].append(t_base_ms)

        # 2. Original-frame multiscale inference + Class-Aware NMS
        t0 = time.perf_counter()
        tiled_res = detector.detect_vehicles(prep)
        t_tiled_ms = (time.perf_counter() - t0) * 1000.0

        tiled_m = sum(1 for v in tiled_res.vehicles if v.cls_name == "motorcycle")
        tiled_c = sum(1 for v in tiled_res.vehicles if v.cls_name == "car")
        delta = len(tiled_res.vehicles) - len(base_vehicles)

        stats_tiled["motorcycles"] += tiled_m
        stats_tiled["cars"] += tiled_c
        stats_tiled["total_vehicles"] += len(tiled_res.vehicles)
        stats_tiled["latencies"].append(t_tiled_ms)
        stats_tiled["deltas"].append(delta)

        base_str = f"{base_m}/{base_c}/{len(base_vehicles)}"
        tiled_str = f"{tiled_m}/{tiled_c}/{len(tiled_res.vehicles)}"
        print(f"{frame_name:<40} | {base_str:<15} | {tiled_str:<20} | {delta:+<6} | {t_tiled_ms:.1f}ms")

    print("-" * 105)
    print("\nBENCHMARK AGGREGATE SUMMARY:")
    print(f"Total Frames Tested: {len(benchmark_subset)}")
    print(f"  • Single Frame (Baseline):")
    print(f"      - Total Motorcycles: {stats_single['motorcycles']}")
    print(f"      - Total Cars:        {stats_single['cars']}")
    print(f"      - Total Vehicles:    {stats_single['total_vehicles']}")
    print(f"      - Avg Latency:       {np.mean(stats_single['latencies']):.2f} ms")
    print(f"  • Original-frame multiscale inference + Class-Aware NMS (Production):")
    print(f"      - Total Motorcycles: {stats_tiled['motorcycles']} (+{(stats_tiled['motorcycles'] - stats_single['motorcycles']) / max(1, stats_single['motorcycles']) * 100:.1f}%)")
    print(f"      - Total Cars:        {stats_tiled['cars']}")
    print(f"      - Total Vehicles:    {stats_tiled['total_vehicles']} (+{(stats_tiled['total_vehicles'] - stats_single['total_vehicles']) / max(1, stats_single['total_vehicles']) * 100:.1f}%)")
    print(f"      - Avg Latency:       {np.mean(stats_tiled['latencies']):.2f} ms")
    print(f"      - Mean Vehicle Gain per Frame: +{np.mean(stats_tiled['deltas']):.2f}\n")

if __name__ == "__main__":
    run_benchmark()

