/**
 * Client API — fetch typé avec refresh JWT automatique.
 *
 * - En SSR, lit le cookie `access_token`.
 * - Sur 401, tente un refresh silencieux via /auth/refresh.
 * - Sur 402 (SUBSCRIPTION_EXPIRED), redirige vers /billing.
 * - Sur 403 (frozen), affiche une bannière.
 */
import type { ApiError, TokenOut } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiException extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiException";
  }
}

// ─── Stockage des tokens (côté client uniquement) ─────────────────────────
const TOKEN_KEY = "mtech_access_token";
const REFRESH_KEY = "mtech_refresh_token";

export const tokenStore = {
  get(): { access: string | null; refresh: string | null } {
    if (typeof window === "undefined") return { access: null, refresh: null };
    return {
      access: localStorage.getItem(TOKEN_KEY),
      refresh: localStorage.getItem(REFRESH_KEY),
    };
  },
  set(tokens: TokenOut) {
    if (typeof window === "undefined") return;
    localStorage.setItem(TOKEN_KEY, tokens.access_token);
    if (tokens.refresh_token) localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  clear() {
    if (typeof window === "undefined") return;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

// ─── Refresh en cours (évite les appels concurrents) ──────────────────────
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const { refresh } = tokenStore.get();
    if (!refresh) return null;
    try {
      const r = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!r.ok) {
        tokenStore.clear();
        return null;
      }
      const tokens: TokenOut = await r.json();
      tokenStore.set(tokens);
      return tokens.access_token;
    } catch {
      return null;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

// ─── API principale ────────────────────────────────────────────────────────
interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  skipAuth?: boolean;
  raw?: boolean; // si true, retourne la Response brute (pour upload)
}

export async function api<T = unknown>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const { body, skipAuth, raw, headers, ...rest } = opts;
  const { access } = tokenStore.get();

  const finalHeaders = new Headers(headers);
  if (!finalHeaders.has("Content-Type") && body && !(body instanceof FormData)) {
    finalHeaders.set("Content-Type", "application/json");
  }
  if (access && !skipAuth) {
    finalHeaders.set("Authorization", `Bearer ${access}`);
  }

  const requestBody =
    body instanceof FormData
      ? body
      : body != null
      ? JSON.stringify(body)
      : undefined;

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: requestBody,
    credentials: "include",
  });

  // ─── 401 : tentative de refresh ────────────────────────────────────────
  if (response.status === 401 && !skipAuth) {
    const newAccess = await refreshAccessToken();
    if (newAccess) {
      finalHeaders.set("Authorization", `Bearer ${newAccess}`);
      const retry = await fetch(`${API_BASE}${path}`, {
        ...rest,
        headers: finalHeaders,
        body: requestBody,
      });
      return handleResponse<T>(retry, raw);
    }
    tokenStore.clear();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new ApiException(401, "UNAUTHORIZED", "Session expirée");
  }

  // ─── 402 : abonnement expiré ───────────────────────────────────────────
  if (response.status === 402) {
    const err: ApiError = await response.json().catch(() => ({
      code: "SUBSCRIPTION_EXPIRED",
      message: "Abonnement expiré",
    }));
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/billing")) {
      window.location.href = "/billing?expired=1";
    }
    throw new ApiException(402, err.code, err.message, err.details);
  }

  return handleResponse<T>(response, raw);
}

async function handleResponse<T>(response: Response, raw?: boolean): Promise<T> {
  if (raw) return response as unknown as T;

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const data = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const err: ApiError =
      typeof data === "object" && data?.message
        ? data
        : {
            code: "HTTP_ERROR",
            message: typeof data === "string" ? data : `Erreur ${response.status}`,
          };
    throw new ApiException(response.status, err.code, err.message, err.details);
  }

  return data as T;
}

// ─── Helpers pratiques ────────────────────────────────────────────────────
export const apiGet = <T>(path: string, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: "GET" });

export const apiPost = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: "POST", body });

export const apiPatch = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: "PATCH", body });

export const apiDelete = <T>(path: string, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: "DELETE" });

export const apiUpload = <T>(path: string, formData: FormData, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: "POST", body: formData });
