/**
 * Helpers pour appeler directement l'API backend depuis les tests
 * (seeding, cleanup, vérifications hors UI).
 */
import type { APIRequestContext } from "@playwright/test";

const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

export interface LoginResult {
  access_token: string;
  refresh_token?: string;
  mfa_required?: boolean;
  session_token?: string;
}

export async function apiLogin(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<LoginResult> {
  const r = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email, password },
  });
  if (!r.ok()) throw new Error(`apiLogin failed: ${r.status()} ${await r.text()}`);
  return r.json();
}

export async function apiLoginWithMfa(
  request: APIRequestContext,
  email: string,
  password: string,
  mfaCode: string,
): Promise<LoginResult> {
  const login = await apiLogin(request, email, password);
  if (!login.mfa_required) return login;

  const r = await request.post(`${API_URL}/api/v1/auth/mfa/verify`, {
    data: { email, code: mfaCode, session_token: login.session_token },
  });
  if (!r.ok()) throw new Error(`MFA verify failed: ${r.status()} ${await r.text()}`);
  return r.json();
}

export function bearerHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export async function apiCreateEcriture(
  request: APIRequestContext,
  token: string,
  payload: {
    date_ecriture: string;
    code_journal: string;
    libelle: string;
    lignes: Array<{ compte: string; debit: number; credit: number }>;
  },
) {
  const r = await request.post(`${API_URL}/api/v1/ecritures`, {
    headers: bearerHeaders(token),
    data: { source: "manuel", ...payload },
  });
  if (!r.ok()) throw new Error(`apiCreateEcriture failed: ${r.status()} ${await r.text()}`);
  return r.json();
}

export async function apiListEcritures(
  request: APIRequestContext,
  token: string,
): Promise<{ items: unknown[]; total: number }> {
  const r = await request.get(`${API_URL}/api/v1/ecritures?page_size=200`, {
    headers: bearerHeaders(token),
  });
  if (!r.ok()) throw new Error(`apiListEcritures failed: ${r.status()}`);
  return r.json();
}
