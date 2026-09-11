// Migration Plan Phase 9 (ADR-018): the ONE real fetch wrapper every
// request in this app goes through. No authentication library, no
// token of any kind read, stored, or attached here — `credentials:
// "include"` is the entire mechanism, sending whatever HttpOnly session
// cookie Container Apps' own Easy Auth already set on the BFF's origin
// (a real interactive sign-in, see AuthGate.tsx). If a caller ever adds
// an `Authorization` header here, that is the exact silent reversal
// ADR-018 warns about — don't be that someone.

// Real finding (see bff/main.py's own module docstring): Easy Auth
// blocks cross-origin CORS preflight before this app's own code ever
// runs, so the real, working shape is this app served SAME-ORIGIN by
// the BFF (a StaticFiles mount) — an unset/empty base URL means
// relative fetches, which resolve correctly against whatever origin
// this build is actually served from. Only set VITE_ONEPULSE_BFF_
// BASE_URL for pointing `npm run dev` at a specific absolute origin
// (useful for UI-only iteration on GET-driven views; POST calls will
// still hit the same real Easy Auth preflight block cross-origin).
const BASE_URL = (import.meta.env.VITE_ONEPULSE_BFF_BASE_URL as string) || "";

export class UnauthenticatedError extends Error {
  constructor() {
    super("Not signed in.");
    this.name = "UnauthenticatedError";
  }
}

// Every real, structured error body this backend actually returns
// ({"error": "...", ...}) — thrown as a typed error so callers can
// branch on `.code` rather than re-parsing JSON or matching on status
// codes scattered across the app.
export class ApiError extends Error {
  status: number;
  code: string | undefined;
  body: unknown;

  constructor(status: number, code: string | undefined, body: unknown) {
    super(typeof body === "object" && body && "message" in body ? String((body as { message: unknown }).message) : `Request failed with ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (res.status === 401) {
    // Real Easy Auth behavior (Migration Plan Phase 7, `--action
    // Return401`): no session cookie, or an expired one -> the
    // platform itself returns 401 before the request ever reaches this
    // app's own code. This is the one signal the whole sign-in gate is
    // built around.
    throw new UnauthenticatedError();
  }

  if (!res.ok) {
    let body: unknown = undefined;
    try {
      body = await res.json();
    } catch {
      // A non-JSON error body is itself worth surfacing as-is.
    }
    const code = typeof body === "object" && body && "error" in body ? String((body as { error: unknown }).error) : undefined;
    throw new ApiError(res.status, code, body);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
}

/** The real Easy Auth interactive sign-in entry point — a top-level
 * browser navigation, never a fetch. No `post_login_redirect_uri`
 * override needed: this app is served same-origin by the BFF, so Easy
 * Auth's own default post-login landing ("/") already *is* the app,
 * now genuinely holding a real session cookie for this exact origin.
 */
export function buildSignInUrl(): string {
  return `${BASE_URL}/.auth/login/aad?post_login_redirect_uri=/`;
}

export { BASE_URL };
