/**
 * Tests E2E — cycle de vie des écritures comptables.
 */
import { test, expect } from "../fixtures";

test.describe("Écritures comptables", () => {
  test("liste des écritures accessible", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures");
    await expect(authenticatedPageA.getByRole("heading", { name: /écritures/i })).toBeVisible();
    await expect(authenticatedPageA.getByRole("link", { name: /nouvelle écriture/i })).toBeVisible();
  });

  test("création d'une écriture équilibrée", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures/new");

    // Remplir le formulaire
    await authenticatedPageA.getByLabel("Libellé").fill("Vente test E2E — 100 000 FCFA");

    // Première ligne : débit
    const selects = authenticatedPageA.locator("select");
    await selects.nth(0).selectOption("521100");  // Banque MM
    const debitInputs = authenticatedPageA.locator('input[type="number"]');
    await debitInputs.nth(0).fill("100000");

    // Deuxième ligne : crédit
    await selects.nth(1).selectOption("701100");  // Ventes
    await debitInputs.nth(1).fill("100000");

    // Vérifier l'indicateur d'équilibre
    await expect(authenticatedPageA.getByText(/écriture équilibrée/i)).toBeVisible();

    // Soumettre
    await authenticatedPageA.getByRole("button", { name: /créer l'écriture/i }).click();

    // Doit rediriger vers la liste
    await expect(authenticatedPageA).toHaveURL(/\/ecritures(?!\/new)/, { timeout: 10_000 });

    // L'écriture doit apparaître dans la liste
    await expect(authenticatedPageA.getByText(/vente test e2e/i).first()).toBeVisible();
  });

  test("création d'une écriture déséquilibrée → bloquée", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures/new");

    await authenticatedPageA.getByLabel("Libellé").fill("Test déséquilibre E2E");

    const selects = authenticatedPageA.locator("select");
    await selects.nth(0).selectOption("521100");
    const numbers = authenticatedPageA.locator('input[type="number"]');
    await numbers.nth(0).fill("100000");

    await selects.nth(1).selectOption("701100");
    await numbers.nth(1).fill("90000");   // déséquilibre volontaire

    // L'indicateur affiche le déséquilibre
    await expect(authenticatedPageA.getByText(/écart/i)).toBeVisible();

    // Le bouton doit refuser la création via validation UI
    await authenticatedPageA.getByRole("button", { name: /créer l'écriture/i }).click();

    // On reste sur la page (erreur ou message)
    await expect(authenticatedPageA).toHaveURL(/\/ecritures\/new/);
    // Un message d'erreur doit apparaître
    await expect(authenticatedPageA.getByRole("alert")).toBeVisible();
  });

  test("écriture sans libellé → bloquée", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures/new");

    // On ne remplit pas le libellé
    const selects = authenticatedPageA.locator("select");
    await selects.nth(0).selectOption("521100");
    const numbers = authenticatedPageA.locator('input[type="number"]');
    await numbers.nth(0).fill("100000");
    await selects.nth(1).selectOption("701100");
    await numbers.nth(1).fill("100000");

    await authenticatedPageA.getByRole("button", { name: /créer l'écriture/i }).click();

    await expect(authenticatedPageA.getByRole("alert")).toContainText(/libellé/i);
  });
});
