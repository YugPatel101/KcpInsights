import type { NextConfig } from "next";

// The browser talks only to this Next.js origin; /api/* is proxied to FastAPI so the
// session cookie stays first-party (HttpOnly, SameSite=Lax) and no CORS is needed.
const API_ORIGIN = process.env.KCP_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Pin the root: a stray lockfile in a parent directory must not change module resolution.
  turbopack: { root: process.cwd() },
  experimental: {
    // Local-model agent calls can take longer than the 30 s default proxy timeout.
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
