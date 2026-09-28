"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { apiGet } from "@/lib/api-client";
import type { Ecriture, Page } from "@/lib/types";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatXOF, formatDate } from "@/lib/format";

export default function EcrituresPage() {
  const [data, setData] = useState<Page<Ecriture> | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const r = await apiGet<Page<Ecriture>>(`/api/v1/ecritures?page=${page}&page_size=50`);
      setData(r);
      setLoading(false);
    }
    load();
  }, [page]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Écritures</h1>
          <p className="text-sm text-slate-500">
            {data?.total ?? 0} écriture{data?.total === 1 ? "" : "s"} au total
          </p>
        </div>
        <Link href="/ecritures/new">
          <Button>
            <Plus className="h-4 w-4" />
            Nouvelle écriture
          </Button>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Journal général</CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          {loading ? (
            <div className="px-6 py-12 text-center text-sm text-slate-500">Chargement…</div>
          ) : !data || data.items.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-slate-500">
              Aucune écriture.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-6 py-3 text-left">N° pièce</th>
                  <th className="px-6 py-3 text-left">Date</th>
                  <th className="px-6 py-3 text-left">Libellé</th>
                  <th className="px-6 py-3 text-left">Source</th>
                  <th className="px-6 py-3 text-right">Débit</th>
                  <th className="px-6 py-3 text-right">Statut</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td className="px-6 py-3 font-mono text-xs">{e.numero_piece}</td>
                    <td className="px-6 py-3">{formatDate(e.date_ecriture)}</td>
                    <td className="px-6 py-3 text-slate-700">{e.libelle}</td>
                    <td className="px-6 py-3">
                      <Badge tone="info">{e.source}</Badge>
                    </td>
                    <td className="px-6 py-3 text-right font-mono">
                      {formatXOF(e.lignes.reduce((s, l) => s + l.debit_xof, 0))}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <Badge
                        tone={
                          e.statut === "validee"
                            ? "success"
                            : e.statut === "gelee"
                            ? "danger"
                            : "neutral"
                        }
                      >
                        {e.statut}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>

      {data && data.total_pages > 1 && (
        <div className="flex justify-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Précédent
          </Button>
          <span className="px-4 py-1 text-sm text-slate-600">
            Page {page} / {data.total_pages}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= data.total_pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Suivant
          </Button>
        </div>
      )}
    </div>
  );
}
