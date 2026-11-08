import type { Metadata } from "next";
import { BenchmarkDashboard } from "../../components/benchmark/BenchmarkDashboard";

export const metadata: Metadata = {
  title: "AI Benchmark | SafePathAI",
  description: "Kết quả đánh giá AI, hiệu năng và độ tin cậy có thể kiểm tra lại của SafePathAI.",
};

export default function BenchmarkPage() {
  return <BenchmarkDashboard />;
}
