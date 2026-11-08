"""
SafePathAI Flood Segmentation ONNX Inference Benchmark Tool.

Measures CPU/edge latency distribution (p50, p95, p99) and frames-per-second (FPS)
for data/models/flood_unet.onnx on synthetic tensors only; not an accuracy or production SLA evaluation.
"""

import time
import argparse
import numpy as np
import onnxruntime as ort


def benchmark_model(
    model_path: str = "data/models/flood_unet.onnx",
    warmup: int = 30,
    iterations: int = 150,
):
    print(f"Benchmarking ONNX model: {model_path}")
    session = ort.InferenceSession(model_path)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    # Create synthetic frame batch
    dummy_input = np.random.uniform(0.0, 1.0, (1, 3, 256, 256)).astype(np.float32)

    # Warmup
    for _ in range(warmup):
        _ = session.run([output_name], {input_name: dummy_input})

    # Benchmark loop
    latencies_ms = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = session.run([output_name], {input_name: dummy_input})
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    p50 = float(np.percentile(latencies_ms, 50))
    p95 = float(np.percentile(latencies_ms, 95))
    p99 = float(np.percentile(latencies_ms, 99))
    mean_lat = float(np.mean(latencies_ms))
    fps = 1000.0 / mean_lat

    print("==================================================")
    print(" FLOOD ONNX INFERENCE BENCHMARK RESULTS")
    print("==================================================")
    print(f"Iterations:      {iterations}")
    print(f"Mean Latency:    {mean_lat:.2f} ms")
    print(f"p50 Latency:     {p50:.2f} ms")
    print(f"p95 Latency:     {p95:.2f} ms (synthetic input)")
    print(f"p99 Latency:     {p99:.2f} ms")
    print(f"Throughput:      {fps:.1f} FPS")
    print("SLA/accuracy:    Not evaluated; use scripts.benchmark_vision with a real source frame.")
    print("==================================================")

    return {
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "mean_ms": mean_lat,
        "fps": fps,
        "scope": "SYNTHETIC_LATENCY_ONLY",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="data/models/flood_unet.onnx")
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--iterations", type=int, default=150)
    args = parser.parse_args()

    benchmark_model(args.model, args.warmup, args.iterations)

