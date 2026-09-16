"use client";

import { useQuery } from "@tanstack/react-query";

async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`backend returned ${response.status}`);
  }
  return response.json();
}

export default function Home() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>Stack Exchange Scout</h1>
      <p>
        backend:{" "}
        {isLoading ? "checking..." : isError ? `error (${error.message})` : data?.status}
      </p>
    </main>
  );
}
