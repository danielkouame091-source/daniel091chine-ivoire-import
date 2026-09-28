/**
 * Tests E2E — cockpit fondateur et isolation du rôle.
 */
import { test, expect } from "../fixtures";

test.describe("Cockpit fondateur", () => {
  test("fondateur voit la liste des entreprises", async ({ founderPage }) => {
    await founderPage.goto("/cockpit/tenants");

    await expect(founderPage.getByRole("heading", { name: /entreprises/i })).toBeVisible();
    // Doit au moins voir les 3 tenants seedés
    await expect(founderPage.getByText("e2e-tenant-a")).toBeVisible();
    await expect(founderPage.getByText("e2e-tenant-b")).toBeVisible();
    await expect(founderPage.getByText("e2e-tenant-expired")).toBeVisible();
  });

  test("fondateur voit les stats globales", async ({ founderPage }) => {
    await founderPage.goto("/cockpit");
    await expect(founderPage.getByText(/entreprises/i)).toBeVisible();
    await expect(founderPage.getByText(/utilisateurs/i)).toBeVisible();
    await expect(founderPage.getByText(/écritures/i)).toBeVisible();
  });

  test("admin tenant ne peut PAS accéder au cockpit (404)", async ({ authenticatedPageA }) => {
    // Tentative d'accès direct
    const response = await authenticatedPageA.goto("/cockpit");
    // Le middleware client redirige, mais si contourné, l'API refuse.
    // On vérifie qu'il n'est PAS sur /cockpit après chargement
    await authenticatedPageA.waitForLoadState("networkidle");
    expect(authenticatedPageA.url()).not.toMatch(/\/cockpit/);
  });

  test("admin tenant est redirigé vers /dashboard s'il tente /cockpit", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/cockpit/tenants");
    await expect(authenticatedPageA).toHaveURL(/\/dashboard/, { timeout: 5_000 });
  });
});
