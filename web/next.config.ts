import type { NextConfig } from "next";

// The Python API (python -m dse_screener api). Browser requests to /api/* are proxied there,
// so the frontend and API share one origin and the API stays on localhost.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
