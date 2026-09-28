/**
 * Tests E2E — flux d'authentification.
 * 1. Login réussi (sans MFA)
 * 2. Login échoué (mauvais mot de passe)
 * 3. Login fondateur → redirection MFA
 * 4. MFA correct → cockpit
 * 5. MFA incorrect → message d'erreur
 * 6. Route protégée sans token → redirection /login
 */
import { test, expect } from "../fixtures";

test.describe("Authentification", () => {
  test("login tenant A réussi → dashboard", async ({ page, credentials }) => {
    await page.goto("/login");
    await page.getByLabel("Adresse e-mail").fill(credentials.tenant_a.email);
    await page.getByLabel("Mot de passe").fill(credentials.tenant_a.password);
    await page.getByRole("button", { name: /se connecter/i }).click();

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: /tableau de bord/i })).toBeVisible();
  });

  test("login avec mauvais mot de passe → erreur", async ({ page, credentials }) => {
    await page.goto("/login");
    await page.getByLabel("Adresse e-mail").fill(credentials.tenant_a.email);
    await page.getByLabel("Mot de passe").fill("MauvaisMotDePasse!999");
    await page.getByRole("button", { name: /se connecter/i }).click();

    await expect(page.getByRole("alert")).toContainText(/identifiants invalides/i);
    await expect(page).toHaveURL(/\/login/);
  });

  test("login fondateur → redirection /mfa", async ({ page, credentials }) => {
    await page.goto("/login");
    await page.getByLabel("Adresse e-mail").fill(credentials.founder.email);
    await page.getByLabel("Mot de passe").fill(credentials.founder.password);
    await page.getByRole("button", { name: /se connecter/i }).click();

    await expect(page).toHaveURL(/\/mfa/, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: /vérification en 2 étapes/i })).toBeVisible();
  });

  test("MFA correct → cockpit fondateur", async ({ page, credentials }) => {
    const { TOTP } = await import("otpauth");

    await page.goto("/login");
    await page.getByLabel("Adresse e-mail").fill(credentials.founder.email);
    await page.getByLabel("Mot de passe").fill(credentials.founder.password);
    await page.getByRole("button", { name: /se connecter/i }).click();
    await expect(page).toHaveURL(/\/mfa/);

    const totp = new TOTP({ secret: credentials.founder.mfa_secret, digits: 6, period: 30 });
    const code = totp.generate();

    await page.getByLabel("Code").or(page.getByPlaceholder("000000")).fill(code);
    await page.getByRole("button", { name: /vérifier/i }).click();

    await expect(page).toHaveURL(/\/cockpit/, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: /vue d'ensemble/i })).toBeVisible();
  });

  test("MFA incorrect → erreur affichée", async ({ page, credentials }) => {
    await page.goto("/login");
    await page.getByLabel("Adresse e-mail").fill(credentials.founder.email);
    await page.getByLabel("Mot de passe").fill(credentials.founder.password);
    await page.getByRole("button", { name: /se connecter/i }).click();
    await expect(page).toHaveURL(/\/mfa/);

    await page.getByPlaceholder("000000").fill("000000");   // code volontairement invalide
    await page.getByRole("button", { name: /vérifier/i }).click();

    await expect(page.getByRole("alert")).toContainText(/code mfa invalide/i);
  });

  test("route protégée sans token → /login", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });
});
