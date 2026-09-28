/**
 * Fixtures Playwright étendues.
 * - `credentials` : credentials seedés par global-setup
 * - `loginAs`      : helper pour se connecter via l'API et injecter le token
 * - `authenticatedPage` : page déjà loggée en tant qu'admin tenant A
 * - `founderPage`  : page déjà loggée en tant que fondateur (avec MFA)
 */
import { test as base, type Page, type APIRequestContext } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { TOTP } from "otpauth";

const CREDENTIALS_FILE = join(process.cwd(), "tests-e2e", ".fixtures", "credentials.json");

interface Credentials {
  founder: { email: string; password: string; mfa_secret: string };
  tenant_a: { slug: string; tenant_id: string; email: string; password: string };
  tenant_b: { slug: string; tenant_id: string; email: string; password: string };
  tenant_expired: { slug: string; tenant_id: string; email: string; password: string };
}

function loadCredentials(): Credentials {
  return JSON.parse(readFileSync(CREDENTIALS_FILE, "utf-8"));
}

// ─── Helper : login via API + pose des cookies + localStorage ─────────────
async function performLogin(
  page: Page,
  request: APIRequestContext,
  email: string,
  password: string,
  mfaSecret?: string,
): Promise<void> {
  const apiUrl = process.env.E2E_API_URL ?? "http://localhost:8000";

  const loginRes = await request.post(`${apiUrl}/api/v1/auth/login`, {
    data: { email, password },
  });
  if (!loginRes.ok()) {
    throw new Error(`Login échoué (${loginRes.status()}): ${await loginRes.text()}`);
  }
  const loginData = await loginRes.json();

  let tokens = loginData;

  // Si MFA requis → on génère le code TOTP et on vérifie
  if (loginData.mfa_required) {
    if (!mfaSecret) throw new Error("MFA requis mais aucun secret fourni");
    const totp = new TOTP({ secret: mfaSecret, digits: 6, period: 30 });
    const code = totp.generate();

    const mfaRes = await request.post(`${apiUrl}/api/v1/auth/mfa/verify`, {
      data: {
        email,
        code,
        session_token: loginData.session_token,
      },
    });
    if (!mfaRes.ok()) {
      throw new Error(`MFA verify échoué (${mfaRes.status()}): ${await mfaRes.text()}`);
    }
    tokens = await mfaRes.json();
  }

  // Injection dans le contexte navigateur
  await page.context().addCookies([
    {
      name: "mtech_access_token",
      value: tokens.access_token,
      domain: "localhost",
      path: "/",
      httpOnly: false,
      secure: false,
      sameSite: "Lax",
    },
  ]);

  await page.goto("/");
  await page.evaluate(
    ({ access, refresh }) => {
      localStorage.setItem("mtech_access_token", access);
      if (refresh) localStorage.setItem("mtech_refresh_token", refresh);
    },
    { access: tokens.access_token, refresh: tokens.refresh_token },
  );
}

// ─── Fixtures ─────────────────────────────────────────────────────────────
type Fixtures = {
  credentials: Credentials;
  loginAsTenantA: () => Promise<void>;
  loginAsFounder: () => Promise<void>;
  authenticatedPageA: Page;
  founderPage: Page;
};

export const test = base.extend<Fixtures>({
  credentials: async ({}, use) => {
    await use(loadCredentials());
  },

  loginAsTenantA: async ({ page, request, credentials }, use) => {
    await use(async () => {
      await performLogin(page, request, credentials.tenant_a.email, credentials.tenant_a.password);
    });
  },

  loginAsFounder: async ({ page, request, credentials }, use) => {
    await use(async () => {
      await performLogin(
        page,
        request,
        credentials.founder.email,
        credentials.founder.password,
        credentials.founder.mfa_secret,
      );
    });
  },

  authenticatedPageA: async ({ page, request, credentials }, use) => {
    await performLogin(page, request, credentials.tenant_a.email, credentials.tenant_a.password);
    await use(page);
  },

  founderPage: async ({ page, request, credentials }, use) => {
    await performLogin(
      page,
      request,
      credentials.founder.email,
      credentials.founder.password,
      credentials.founder.mfa_secret,
    );
    await use(page);
  },
});

export { expect } from "@playwright/test";
