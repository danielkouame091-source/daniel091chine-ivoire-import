/**
 * Nettoyage optionnel après les tests.
 * Ne supprime RIEN côté DB (le seed est idempotent).
 */
export default async function globalTeardown() {
  console.log("[E2E] Teardown — données laissées en place (seed idempotent).");
}
