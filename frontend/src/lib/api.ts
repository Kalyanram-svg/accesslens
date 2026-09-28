/** Typed fetch wrapper. The token lives in memory + sessionStorage; the backend is always authoritative. */
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const KEY = "nt-session";

let token: string | null = null;
try {
  token = sessionStorage.getItem(KEY);
} catch {
  token = null;
}

export function setToken(t: string | null) {
  token = t;
  try {
    if (t) sessionStorage.setItem(KEY, t);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable — keep in memory */
  }
}
export const getToken = () => token;

export type Why = { your_role?: string; required_permission?: string; resource?: string; recommended_action?: string };

export class ApiError extends Error {
  status: number;
  code: string;
  why?: Why;
  constructor(status: number, code: string, message: string, why?: Why) {
    super(message);
    this.status = status;
    this.code = code;
    this.why = why;
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Can't reach the NovaTech API. Check that the backend is running.");
  }
  if (res.status === 401 && path !== "/api/auth/login") {
    onUnauthorized?.();
  }
  if (!res.ok) {
    let detail: { code?: string; message?: string; why?: Why } = {};
    try {
      detail = (await res.json()).detail ?? {};
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail.code ?? "ERROR", detail.message ?? "Something went wrong.", detail.why);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as unknown)) as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T,>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  upload: <T,>(p: string, form: FormData) => request<T>("POST", p, form, true),
};

export async function download(path: string, filename: string) {
  const blob = await request<Blob>("GET", path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Server-Sent Events over fetch (EventSource can't send the Authorization header). */
export async function streamRun(runId: number, onEvent: (event: string, data: any) => void, signal?: AbortSignal) {
  const res = await fetch(`${BASE}/api/agent/runs/${runId}/stream`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, "STREAM", "Live agent updates are unavailable.");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = /event: (.*)/.exec(chunk)?.[1] ?? "message";
      const data = /data: (.*)/s.exec(chunk)?.[1];
      if (data) onEvent(ev, JSON.parse(data));
    }
  }
}
