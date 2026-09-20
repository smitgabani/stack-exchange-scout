import type { NextConfig } from "next";

// Server-only (no NEXT_PUBLIC_ prefix) — the browser never sees this URL.
// Requests go to our own origin at /api/*, which Vercel proxies server-side
// to the real FastAPI backend. This keeps the session cookie same-site from
// the browser's perspective instead of a genuine cross-domain cookie.
const backendUrl = process.env.BACKEND_URL;

const nextConfig: NextConfig = {
  // Scout and Accounts moved under /yutori. Temporary (307) rather than
  // permanent: a 308 is cached by the browser indefinitely, which is painful
  // to undo if the structure changes again while the app is still growing.
  async redirects() {
    return [
      { source: "/scout", destination: "/yutori/scouts", permanent: false },
      { source: "/scout/monitors", destination: "/yutori/monitors", permanent: false },
      { source: "/scout/runs/:runId", destination: "/yutori/runs/:runId", permanent: false },
      // Must come after the two literal paths above, or it would swallow them.
      { source: "/scout/:id", destination: "/yutori/scouts/:id", permanent: false },
      { source: "/accounts", destination: "/yutori/accounts", permanent: false },
      { source: "/accounts/:id", destination: "/yutori/accounts/:id", permanent: false },
    ];
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
