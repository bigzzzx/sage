import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.SAGE_NEXT_DIST_DIR || ".next",
  async rewrites() {
    const backendUrl = (process.env.SAGE_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
