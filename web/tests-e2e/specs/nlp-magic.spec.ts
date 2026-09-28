/**
 * Tests E2E — saisie magique via IA (différenciateur produit).
 * ⚠️ Ces tests dépendent de l'IA côté backend.
 *    Si OPENAI_API_KEY n'est pas définie en test, ils seront skippés.
 */
import { test, expect } from "../fixtures";

test.describe("Saisie magique (IA/NLP)", () => {
  test.skip(
    !process.env.OPENAI_API_KEY && !process.env.E2E_ENABLE_NLP,
    "NLP désactivé (OPENAI_API_KEY absente et E2E_ENABLE_NLP != 1)",
  );

  test("générer une suggestion depuis une phrase simple", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures/new");

    const textarea = authenticatedPageA.getByPlaceholder(/vente de 50 sacs/i);
    await textarea.fill("Vente de 50 sacs de riz à 25 000 FCFA à M. Koné, payé par Wave");

    await authenticatedPageA.getByRole("button", { name: /générer l'écriture/i }).click();

    // Attendre la proposition
    await expect(
      authenticatedPageA.getByText(/proposition de l'ia/i),
    ).toBeVisible({ timeout: 30_000 });

    // Vérifier que l'écriture est équilibrée
    await expect(authenticatedPageA.getByText(/confiance/i)).toBeVisible();
  });

  test("valider une suggestion crée l'écriture", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures/new");

    await authenticatedPageA
      .getByPlaceholder(/vente de 50 sacs/i)
      .fill("Vente de 10 cartons de lait à 15 000 FCFA à Mme Diallo, payé par Orange Money");

    await authenticatedPageA.getByRole("button", { name: /générer l'écriture/i }).click();
    await expect(authenticatedPageA.getByText(/proposition de l'ia/i)).toBeVisible({
      timeout: 30_000,
    });

    await authenticatedPageA
      .getByRole("button", { name: /valider et comptabiliser/i })
      .click();

    // Redirection vers la liste
    await expect(authenticatedPageA).toHaveURL(/\/ecritures(?!\/new)/, { timeout: 10_000 });
  });

  test("rejeter une suggestion la supprime de l'écran", async ({ authenticatedPageA }) => {
    await authenticatedPageA.goto("/ecritures/new");

    await authenticatedPageA
      .getByPlaceholder(/vente de 50 sacs/i)
      .fill("Achat de fournitures 50 000 FCFA");

    await authenticatedPageA.getByRole("button", { name: /générer l'écriture/i }).click();
    await expect(authenticatedPageA.getByText(/proposition de l'ia/i)).toBeVisible({
      timeout: 30_000,
    });

    await authenticatedPageA.getByRole("button", { name: /rejeter/i }).click();

    await expect(authenticatedPageA.getByText(/proposition de l'ia/i)).not.toBeVisible();
  });
});
