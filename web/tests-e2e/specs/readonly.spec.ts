/**
 * Tests E2E — bascule automatique en mode lecture seule quand l'abonnement
 * est expiré.
 */
import { test, expect } from "../fixtures";

test.describe("Mode lecture seule (abonnement expiré)", () => {
  test("bannière read-only visible sur le dashboard", async ({ page, request, credentials }) => {
    // Login en tant qu'admin du tenant expiré
    const { apiLogin } = await import("../helpers/api");
    const tokens = await apiLogin(request, credentials.tenant_expired.email, credentials.tenant_expired.password);

    await page.context().addCookies([
      {
        name: "mtech_access_token",
        value: tokens.access_token,
        domain: "localhost",
        path: "/",
        sameSite: "Lax",
      },
    ]);
    await page.goto("/");
    await page.evaluate((access) => {
      localStorage.setItem("mtech_access_token", access);
    }, tokens.access_token);

    await page.goto("/dashboard");

    // Bannière read-only attendue
    await expect(page.getByText(/abonnement expiré/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: /renouveler/i })).toBeVisible();
  });

  test("création d'écriture bloquée par l'API (402)", async ({ request, credentials }) => {
    const { apiLogin, bearerHeaders } = await import("../helpers/api");
    const tokens = await apiLogin(request, credentials.tenant_expired.email, credentials.tenant_expired.password);

    const r = await request.post(
      `${process.env.E2E_API_URL ?? "http://localhost:8000"}/api/v1/ecritures`,
      {
        headers: bearerHeaders(tokens.access_token),
        data: {
          date_ecriture: new Date().toISOString().slice(0, 10),
          code_journal: "VE",
          libelle: "Tentative en read-only",
          lignes: [
            { compte: "521100", debit: 1000, credit: 0 },
            { compte: "701100", debit: 0, credit: 1000 },
          ],
          source: "manuel",
        },
      },
    );

    expect(r.status()).toBe(402);
    const body = await r.json();
    expect(body.code).toBe("SUBSCRIPTION_EXPIRED");
  });

  test("consultation d'écritures reste possible en read-only", async ({ request, credentials }) => {
    const { apiLogin, bearerHeaders } = await import("../helpers/api");
    const tokens = await apiLogin(request, credentials.tenant_expired.email, credentials.tenant_expired.password);

    const r = await request.get(
      `${process.env.E2E_API_URL ?? "http://localhost:8000"}/api/v1/ecritures`,
      { headers: bearerHeaders(tokens.access_token) },
    );
    expect(r.status()).toBe(200);   // lecture autorisée
  });
});
