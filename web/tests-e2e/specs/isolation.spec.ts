/**
 * ⚠️ TESTS CRITIQUES — isolation stricte cross-tenant.
 * Vérifie que le tenant A ne peut JAMAIS voir les données du tenant B,
 * même en manipulant directement l'API.
 */
import { test, expect } from "../fixtures";

test.describe("Isolation multi-tenant (RLS)", () => {
  test("tenant A ne voit PAS les écritures du tenant B (via API)", async ({
    request,
    credentials,
  }) => {
    const { apiLogin, bearerHeaders, apiCreateEcriture, apiListEcritures } = await import("../helpers/api");

    const today = new Date().toISOString().slice(0, 10);

    // ─── Login tenant A + création écriture A ─────────────────────
    const tokensA = await apiLogin(request, credentials.tenant_a.email, credentials.tenant_a.password);
    const ecritureA = await apiCreateEcriture(request, tokensA.access_token, {
      date_ecriture: today,
      code_journal: "VE",
      libelle: "E2E-ISOLATION-TENANT-A",
      lignes: [
        { compte: "521100", debit: 111_000, credit: 0 },
        { compte: "701100", debit: 0, credit: 111_000 },
      ],
    });

    // ─── Login tenant B + création écriture B ─────────────────────
    const tokensB = await apiLogin(request, credentials.tenant_b.email, credentials.tenant_b.password);
    const ecritureB = await apiCreateEcriture(request, tokensB.access_token, {
      date_ecriture: today,
      code_journal: "VE",
      libelle: "E2E-ISOLATION-TENANT-B",
      lignes: [
        { compte: "521100", debit: 222_000, credit: 0 },
        { compte: "701100", debit: 0, credit: 222_000 },
      ],
    });

    expect(ecritureA.id).not.toBe(ecritureB.id);

    // ─── Vérifier isolation ───────────────────────────────────────
    const listA = await apiListEcritures(request, tokensA.access_token);
    const idsA = (listA.items as Array<{ id: string }>).map((e) => e.id);

    const listB = await apiListEcritures(request, tokensB.access_token);
    const idsB = (listB.items as Array<{ id: string }>).map((e) => e.id);

    // A voit sa propre écriture
    expect(idsA).toContain(ecritureA.id);
    // A ne voit JAMAIS celle de B
    expect(idsA).not.toContain(ecritureB.id);

    // B voit la sienne
    expect(idsB).toContain(ecritureB.id);
    expect(idsB).not.toContain(ecritureA.id);
  });

  test("tenant A ne peut pas lire une écriture de B par ID direct", async ({
    request,
    credentials,
  }) => {
    const { apiLogin, bearerHeaders, apiCreateEcriture } = await import("../helpers/api");
    const apiUrl = process.env.E2E_API_URL ?? "http://localhost:8000";
    const today = new Date().toISOString().slice(0, 10);

    // Créer une écriture pour B
    const tokensB = await apiLogin(request, credentials.tenant_b.email, credentials.tenant_b.password);
    const ecritureB = await apiCreateEcriture(request, tokensB.access_token, {
      date_ecriture: today,
      code_journal: "VE",
      libelle: "E2E-PRIVATE-B",
      lignes: [
        { compte: "521100", debit: 333_000, credit: 0 },
        { compte: "701100", debit: 0, credit: 333_000 },
      ],
    });

    // Tenant A tente d'y accéder par ID
    const tokensA = await apiLogin(request, credentials.tenant_a.email, credentials.tenant_a.password);
    const r = await request.get(`${apiUrl}/api/v1/ecritures/${ecritureB.id}`, {
      headers: bearerHeaders(tokensA.access_token),
    });

    // Doit renvoyer 404 (RLS ne laisse pas passer)
    expect(r.status()).toBe(404);
  });

  test("admin tenant A ne voit PAS les users du tenant B", async ({ request, credentials }) => {
    const { apiLogin, bearerHeaders } = await import("../helpers/api");
    const apiUrl = process.env.E2E_API_URL ?? "http://localhost:8000";

    const tokensA = await apiLogin(request, credentials.tenant_a.email, credentials.tenant_a.password);
    const r = await request.get(`${apiUrl}/api/v1/users`, {
      headers: bearerHeaders(tokensA.access_token),
    });
    expect(r.status()).toBe(200);

    const users = await r.json();
    // Aucun user ne doit avoir l'email du tenant B
    const emails = (users as Array<{ email: string }>).map((u) => u.email);
    expect(emails).not.toContain(credentials.tenant_b.email);
  });

  test("tenant A ne peut PAS accéder aux routes cockpit", async ({ request, credentials }) => {
    const { apiLogin, bearerHeaders } = await import("../helpers/api");
    const apiUrl = process.env.E2E_API_URL ?? "http://localhost:8000";

    const tokensA = await apiLogin(request, credentials.tenant_a.email, credentials.tenant_a.password);
    const r = await request.get(`${apiUrl}/api/v1/cockpit/tenants`, {
      headers: bearerHeaders(tokensA.access_token),
    });

    // Le fondateur guard renvoie 404 (pas 403) pour ne pas révéler le cockpit
    expect(r.status()).toBe(404);
  });
});
