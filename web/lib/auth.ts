/**
 * Helpers d'authentification côté client + lecture user depuis JWT.
 */
import type { CurrentUser, TokenOut } from "./types";
import { tokenStore } from "./api-client";

export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

export function isTokenExpired(token: string): boolean {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") return true;
  return payload.exp * 1000 < Date.now();
}

export function getStoredUser(): CurrentUser | null {
  const { access } = tokenStore.get();
  if (!access || isTokenExpired(access)) return null;
  const payload = decodeJwtPayload(access);
  if (!payload) return null;
  return {
    id: String(payload.sub ?? ""),
    email: String(payload.email ?? ""),
    nom_complet: String(payload.nom_complet ?? ""),
    role: (payload.role as CurrentUser["role"]) ?? "LECTEUR",
    is_founder: Boolean(payload.is_founder),
    tenant_id: (payload.tenant_id as string | null) ?? null,
    mfa_enabled: Boolean(payload.mfa_enabled),
    derniere_connexion: null,
  };
}

export function saveTokens(tokens: TokenOut) {
  tokenStore.set(tokens);
}

export function logout() {
  tokenStore.clear();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}
