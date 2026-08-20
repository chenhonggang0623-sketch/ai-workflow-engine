import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // /api/planner/plan 等接口依赖 LLM，响应可能超过 1 分钟；
    // dev 代理默认 30s 超时会导致 socket hang up (500)。
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
