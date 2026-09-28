"use client";

import { Trash2, Plus } from "lucide-react";
import type { LigneIn } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { formatXOF } from "@/lib/format";

interface Props {
  lignes: LigneIn[];
  planComptes: Array<{ compte: string; libelle: string }>;
  onChange: (lignes: LigneIn[]) => void;
}

export function LigneEditor({ lignes, planComptes, onChange }: Props) {
  function update(index: number, patch: Partial<LigneIn>) {
    const next = [...lignes];
    next[index] = { ...next[index], ...patch };
    // Règle : si on saisit un débit, on annule le crédit et vice-versa
    if (patch.debit !== undefined && patch.debit > 0) next[index].credit = 0;
    if (patch.credit !== undefined && patch.credit > 0) next[index].debit = 0;
    onChange(next);
  }

  function add() {
    onChange([...lignes, { compte: "", libelle: "", debit: 0, credit: 0 }]);
  }

  function remove(index: number) {
    if (lignes.length <= 2) return;
    onChange(lignes.filter((_, i) => i !== index));
  }

  const totalDebit = lignes.reduce((s, l) => s + (l.debit || 0), 0);
  const totalCredit = lignes.reduce((s, l) => s + (l.credit || 0), 0);
  const equilibre = totalDebit === totalCredit && totalDebit > 0;

  return (
    <div className="space-y-3">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-2 py-2 text-left">Compte</th>
            <th className="px-2 py-2 text-left">Libellé</th>
            <th className="px-2 py-2 text-right">Débit (XOF)</th>
            <th className="px-2 py-2 text-right">Crédit (XOF)</th>
            <th className="w-10"></th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((l, i) => (
            <tr key={i} className="border-b border-slate-50">
              <td className="px-2 py-1">
                <select
                  value={l.compte}
                  onChange={(e) => update(i, { compte: e.target.value })}
                  className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                >
                  <option value="">— Choisir —</option>
                  {planComptes.map((p) => (
                    <option key={p.compte} value={p.compte}>
                      {p.compte} — {p.libelle}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-2 py-1">
                <input
                  type="text"
                  value={l.libelle ?? ""}
                  onChange={(e) => update(i, { libelle: e.target.value })}
                  className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                />
              </td>
              <td className="px-2 py-1">
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={l.debit || ""}
                  onChange={(e) => update(i, { debit: parseInt(e.target.value, 10) || 0 })}
                  className="w-full rounded border border-slate-300 px-2 py-1 text-right font-mono text-xs"
                />
              </td>
              <td className="px-2 py-1">
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={l.credit || ""}
                  onChange={(e) => update(i, { credit: parseInt(e.target.value, 10) || 0 })}
                  className="w-full rounded border border-slate-300 px-2 py-1 text-right font-mono text-xs"
                />
              </td>
              <td className="px-2 py-1 text-right">
                <button
                  onClick={() => remove(i)}
                  disabled={lignes.length <= 2}
                  className="rounded p-1 text-slate-400 hover:bg-danger-50 hover:text-danger-700 disabled:opacity-30"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t-2 border-slate-200 font-semibold">
          <tr>
            <td colSpan={2} className="px-2 py-2 text-right text-xs uppercase text-slate-500">
              Totaux
            </td>
            <td className="px-2 py-2 text-right font-mono">{formatXOF(totalDebit)}</td>
            <td className="px-2 py-2 text-right font-mono">{formatXOF(totalCredit)}</td>
            <td></td>
          </tr>
        </tfoot>
      </table>

      <div className="flex items-center justify-between">
        <Button onClick={add} variant="secondary" size="sm">
          <Plus className="h-4 w-4" />
          Ajouter une ligne
        </Button>
        <span
          className={`text-xs font-medium ${
            equilibre ? "text-success-700" : "text-danger-700"
          }`}
        >
          {equilibre ? "✓ Écriture équilibrée" : `Écart : ${formatXOF(totalDebit - totalCredit)}`}
        </span>
      </div>
    </div>
  );
}
