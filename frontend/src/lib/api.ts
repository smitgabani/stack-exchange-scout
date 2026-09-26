/**
 * The one fetch wrapper every client and page uses.
 *
 * Thrown for any non-2xx answer: `message` is the backend's plain `detail`
 * (or `detail.message` when the detail is structured), so
 * `(error as Error).message` reads as the backend wrote it; `status` and
 * `detail` are there for the few callers that need to act on the answer.
 */
export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** Parses the body (an empty 204 reads as `{}`) and throws `ApiError` on failure. */
export async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof (detail as { message?: unknown } | null)?.message === "string"
          ? (detail as { message: string }).message
          : `${path} failed (${response.status})`;
    throw new ApiError(message, response.status, detail);
  }
  return body as T;
}

/** A request with a JSON body, or with none when `body` is omitted. */
export const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});
