import type { NextConfig } from "next";

// Server-only (no NEXT_PUBLIC_ prefix) — the browser never sees this URL.
// Requests go to our own origin at /api/*, which Vercel proxies server-side
// to the real FastAPI backend. This keeps the session cookie same-site from
// the browser's perspective instead of a genuine cross-domain cookie.
const backendUrl = process.env.BACKEND_URL;

const nextConfig: NextConfig = {
  // Inlined at build time, so every page (static or rendered on request) names
  // the commit it was built from. GIT_SHA comes from the deploy pipeline;
  // VERCEL_GIT_COMMIT_SHA covers a build Vercel runs from Git itself.
  env: {
    GIT_SHA: process.env.GIT_SHA || process.env.VERCEL_GIT_COMMIT_SHA || "dev",
  },

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
