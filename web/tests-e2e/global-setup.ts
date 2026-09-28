/**
 * Exécuté une seule fois avant TOUS les tests.
 * - Lance le script Python scripts/seed_e2e.py pour préparer les fixtures
 * - Sauvegarde les credentials dans un fichier JSON partagé
 */
import { execSync } from "node:child_process";
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const FIXTURES_DIR = join(process.cwd(), "tests-e2e", ".fixtures");
const CREDENTIALS_FILE = join(FIXTURES_DIR, "credentials.json");

export interface Credentials {
  founder: { email: string; password: string; mfa_secret: string };
  tenant_a: { slug: string; tenant_id: string; email: string; password: string };
  tenant_b: { slug: string; tenant_id: string; email: string; password: string };
  tenant_expired: { slug: string; tenant_id: string; email: string; password: string };
}

export default async function globalSetup() {
  console.log("[E2E] Seed des données de test via scripts/seed_e2e.py…");

  let raw: string;
  try {
    raw = execSync("python -m scripts.seed_e2e", {
      cwd: join(process.cwd(), ".."),   // racine du monorepo (backend)
      env: { ...process.env, PYTHONPATH: "." },
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (err: unknown) {
    const e = err as { stdout?: Buffer; stderr?: Buffer };
    console.error("[E2E] Seed échoué :");
    console.error(e.stdout?.toString() ?? "");
    console.error(e.stderr?.toString() ?? "");
    throw err;
  }

  const data: Credentials = JSON.parse(raw.trim());

  if (!existsSync(FIXTURES_DIR)) mkdirSync(FIXTURES_DIR, { recursive: true });
  writeFileSync(CREDENTIALS_FILE, JSON.stringify(data, null, 2), "utf-8");

  console.log("[E2E] Fixtures prêtes :");
  console.log(`  · Fondateur : ${data.founder.email}`);
  console.log(`  · Tenant A  : ${data.tenant_a.slug}`);
  console.log(`  · Tenant B  : ${data.tenant_b.slug}`);
  console.log(`  · Expiré    : ${data.tenant_expired.slug}`);
}

export { CREDENTIALS_FILE };
