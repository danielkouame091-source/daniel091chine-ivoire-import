"use client";

import { useState } from "react";
import { Sparkles, Check, X } from "lucide-react";
import { apiPost, ApiException } from "@/lib/api-client";
import type { Ecriture, LigneIn } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Card, CardBody } from "@/components/ui/card";
import { formatXOF } from "@/lib/format";
import { toast } from "sonner";

interface Suggestion {
  id: string;
  phrase_source: string;
  ecriture_proposee: {
    numero_piece?: string;
    date_ecriture: string;
    code_journal: string;
    libelle: string;
    lignes: Array<{ compte: string; libelle?: string; debit: number; credit: number }>;
  };
  confiance: number;
  statut: string;
}

interface Props {
  onCreated: (e: Ecriture) => void;
  planComptes: Array<{ compte: string; libelle: string }>;
}

const EXEMPLES = [
  "Vente de 50 sacs de riz à 25 000 FCFA à M. Koné, payé par Wave",
  "Achat de fournitures de bureau 75 000 FCFA chez BureauPlus, à crédit",
  "Encaissement client 250 000 FCFA par Orange Money",
  "Paiement loyer du mois 150 000 FCFA par banque",
];

export function NlpMagicInput({ onCreated, planComptes }: Props) {
  const [phrase, setPhrase] = useState("");
  const [loading, setLoading] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function suggerer() {
    setError(null);
    setLoading(true);
    try {
      const s = await apiPost<Suggestion>("/api/v1/ai/suggerer", {
        phrase,
        langue: "fr",
      });
      setSuggestion(s);
    } catch (err) {
      if (err instanceof ApiException) setError(err.message);
      else setError("Impossible de générer une suggestion.");
    } finally {
      setLoading(false);
    }
  }

  async function accepter() {
    if (!suggestion) return;
    setAccepting(true);
    try {
      const e = await apiPost<Ecriture>(`/api/v1/ai/suggestions/${suggestion.id}/accepter`);
      toast.success(`Écriture ${e.numero_piece} créée`);
      setSuggestion(null);
      setPhrase("");
      onCreated(e);
    } catch (err) {
      if (err instanceof ApiException) toast.error(err.message);
    } finally {
      setAccepting(false);
    }
  }

  function rejeter() {
    setSuggestion(null);
  }

  return (
    <Card className="border-brand-200 bg-gradient-to-br from-brand-50/50 to-white">
      <CardBody className="space-y-4">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-brand-600" />
          <h3 className="text-sm font-semibold text-slate-900">Saisie magique (IA)</h3>
        </div>

        <p className="text-xs text-slate-500">
          Décrivez l'opération en français (ou en langue locale). L'IA la convertit en
          écriture SYSCOHADA équilibrée.
        </p>

        <textarea
          rows={3}
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          placeholder="Ex : Vente de 50 sacs de riz à 25 000 FCFA à M. Koné, payé par Wave"
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />

        <div className="flex flex-wrap gap-2">
          {EXEMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => setPhrase(ex)}
              className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
            >
              {ex.slice(0, 40)}…
            </button>
          ))}
        </div>

        {error && <Alert variant="danger">{error}</Alert>}

        <Button onClick={suggerer} loading={loading} disabled={!phrase.trim()}>
          <Sparkles className="h-4 w-4" />
          Générer l'écriture
        </Button>

        {suggestion && (
          <div className="rounded-md border border-brand-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase text-slate-500">
                Proposition de l'IA
              </span>
              <span
                className={`text-xs font-medium ${
                  suggestion.confiance > 0.8
                    ? "text-success-700"
                    : suggestion.confiance > 0.5
                    ? "text-warning-700"
                    : "text-danger-700"
                }`}
              >
                Confiance : {(suggestion.confiance * 100).toFixed(0)}%
              </span>
            </div>

            <div className="mb-3 space-y-1 text-sm">
              <p>
                <strong>Date :</strong> {suggestion.ecriture_proposee.date_ecriture}
              </p>
              <p>
                <strong>Journal :</strong>{" "}
                <code className="rounded bg-slate-100 px-1 font-mono text-xs">
                  {suggestion.ecriture_proposee.code_journal}
                </code>
              </p>
              <p>
                <strong>Libellé :</strong> {suggestion.ecriture_proposee.libelle}
              </p>
            </div>

            <table className="w-full text-xs">
              <thead className="border-y border-slate-100 text-slate-500">
                <tr>
                  <th className="py-1 text-left">Compte</th>
                  <th className="py-1 text-left">Libellé</th>
                  <th className="py-1 text-right">Débit</th>
                  <th className="py-1 text-right">Crédit</th>
                </tr>
              </thead>
              <tbody>
                {suggestion.ecriture_proposee.lignes.map((l, i) => {
                  const pc = planComptes.find((p) => p.compte === l.compte);
                  return (
                    <tr key={i} className="border-b border-slate-50 last:border-0">
                      <td className="py-1 font-mono">
                        {l.compte}
                        {pc && <span className="ml-1 text-slate-400">({pc.libelle})</span>}
                      </td>
                      <td className="py-1 text-slate-600">{l.libelle ?? "—"}</td>
                      <td className="py-1 text-right font-mono">
                        {l.debit ? formatXOF(l.debit) : "—"}
                      </td>
                      <td className="py-1 text-right font-mono">
                        {l.credit ? formatXOF(l.credit) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="mt-4 flex gap-2">
              <Button onClick={accepter} loading={accepting} variant="success" size="sm">
                <Check className="h-4 w-4" />
                Valider et comptabiliser
              </Button>
              <Button onClick={rejeter} variant="ghost" size="sm">
                <X className="h-4 w-4" />
                Rejeter
              </Button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
