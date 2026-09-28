"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost, ApiException } from "@/lib/api-client";
import type { Ecriture, Journal, LigneIn, PlanComptable } from "@/lib/types";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/alert";
import { LigneEditor } from "@/components/ecriture/LigneEditor";
import { NlpMagicInput } from "@/components/ecriture/NlpMagicInput";
import { toast } from "sonner";

export default function NewEcriturePage() {
  const router = useRouter();
  const [planComptes, setPlanComptes] = useState<PlanComptable[]>([]);
  const [journaux, setJournaux] = useState<Journal[]>([]);
  const [loading, setLoading] = useState(true);

  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [journalCode, setJournalCode] = useState("VE");
  const [libelle, setLibelle] = useState("");
  const [referenceExt, setReferenceExt] = useState("");
  const [lignes, setLignes] = useState<LigneIn[]>([
    { compte: "", libelle: "", debit: 0, credit: 0 },
    { compte: "", libelle: "", debit: 0, credit: 0 },
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [pc, js] = await Promise.all([
          apiGet<PlanComptable[]>("/api/v1/plan-comptable"),
          apiGet<Journal[]>("/api/v1/journaux"),
        ]);
        setPlanComptes(pc);
        setJournaux(js);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!libelle.trim()) return setError("Le libellé est obligatoire.");
    const validLignes = lignes.filter((l) => l.compte && (l.debit > 0 || l.credit > 0));
    if (validLignes.length < 2) return setError("Au moins 2 lignes complètes requises.");

    const td = validLignes.reduce((s, l) => s + l.debit, 0);
    const tc = validLignes.reduce((s, l) => s + l.credit, 0);
    if (td !== tc) return setError(`Écriture déséquilibrée : D=${td} C=${tc}`);

    setSubmitting(true);
    try {
      const created = await apiPost<Ecriture>("/api/v1/ecritures", {
        date_ecriture: date,
        code_journal: journalCode,
        libelle,
        reference_ext: referenceExt || null,
        source: "manuel",
        lignes: validLignes,
      });
      toast.success(`Écriture ${created.numero_piece} créée`);
      router.push("/ecritures");
    } catch (err) {
      if (err instanceof ApiException) setError(err.message);
      else setError("Erreur lors de la création.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <div className="text-sm text-slate-500">Chargement…</div>;
  }

  const planComptesSimple = planComptes.map((p) => ({ compte: p.compte, libelle: p.libelle }));

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Nouvelle écriture</h1>
        <p className="text-sm text-slate-500">
          Saisie manuelle ou via l'IA — partie double SYSCOHADA garantie.
        </p>
      </div>

      <NlpMagicInput
        planComptes={planComptesSimple}
        onCreated={() => router.push("/ecritures")}
      />

      <Card>
        <CardHeader>
          <CardTitle>Saisie manuelle</CardTitle>
        </CardHeader>
        <CardBody>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && <Alert variant="danger">{error}</Alert>}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <Input
                id="date"
                type="date"
                label="Date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">Journal</label>
                <select
                  value={journalCode}
                  onChange={(e) => setJournalCode(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
                  required
                >
                  {journaux.map((j) => (
                    <option key={j.id} value={j.code}>
                      {j.code} — {j.libelle}
                    </option>
                  ))}
                </select>
              </div>
              <Input
                id="ref"
                type="text"
                label="Référence externe"
                placeholder="Facture, bon de commande…"
                value={referenceExt}
                onChange={(e) => setReferenceExt(e.target.value)}
              />
            </div>

            <Input
              id="libelle"
              type="text"
              label="Libellé"
              placeholder="Ex : Vente 50 sacs de riz à M. Koné"
              value={libelle}
              onChange={(e) => setLibelle(e.target.value)}
              required
            />

            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Lignes</label>
              <LigneEditor
                lignes={lignes}
                planComptes={planComptesSimple}
                onChange={setLignes}
              />
            </div>

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => router.push("/ecritures")}
              >
                Annuler
              </Button>
              <Button type="submit" loading={submitting}>
                Créer l'écriture
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
