"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

// Every /api/* call is a Vercel function proxying to a scale-to-zero Fly
// machine, so a request is never free — it costs function CPU on one side and
// possibly a cold start on the other. TanStack's defaults (staleTime 0,
// refetch on every focus and mount, three retries) are tuned for cheap
// same-origin APIs and refetch far more than a single-user tool needs.
const queryConfig = {
  defaultOptions: {
    queries: {
      // A minute-old profile or question list is fine here; mutations
      // invalidate explicitly when something actually changes.
      staleTime: 60_000,
      // Tab-switching is not a reason to re-fetch the whole app.
      refetchOnWindowFocus: false,
      // One retry, not three: a cold or unhappy backend turned each failed
      // query into four requests.
      retry: 1,
    },
  },
};

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient(queryConfig));

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
