import type { NextConfig } from "next";

// Server-only (no NEXT_PUBLIC_ prefix) — the browser never sees this URL.
// Requests go to our own origin at /api/*, which Vercel proxies server-side
// to the real FastAPI backend. This keeps the session cookie same-site from
// the browser's perspective instead of a genuine cross-domain cookie.
const backendUrl = process.env.BACKEND_URL;

const nextConfig: NextConfig = {
  async rewrites() {
    if (!backendUrl) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
