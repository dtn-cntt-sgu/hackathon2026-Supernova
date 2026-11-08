/** @type {import('next').NextConfig} */
import path from "node:path";
import { fileURLToPath } from "node:url";
const nextConfig = {
  outputFileTracingRoot: path.dirname(fileURLToPath(import.meta.url)),
  reactStrictMode: true,
  distDir: process.env.SAFEPATH_NEXT_DIST_DIR || ".next",
  output: "standalone",
  images: {
    remotePatterns: [
      {
        protocol: "http",
        hostname: "localhost",
      },
      {
        protocol: "http",
        hostname: "127.0.0.1",
      },
      {
        protocol: "http",
        hostname: "backend",
      },
      {
        protocol: "https",
        hostname: "giaothong.hochiminhcity.gov.vn",
      },
    ],
  }
};

export default nextConfig;

