"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, Wallet, Snowflake, TrendingUp, Plus } from "lucide-react";
import { apiGet } from "@/lib/api-client";
import type { Ecriture, MmTransaction, Page } from "@/lib/types";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatXOF, formatDate, providerLabel } from "@/lib/format";

export default function DashboardPage() {
  const [ecritures, setEcritures] = useState<Page<Ecriture> | null>(null);
  const [mmTx, setMmTx] = useState<MmTransaction[]>([]);

  useEffect(() => {
    async function load() {
      const [e, m] = await Promise.all([
        apiGet<Page<Ecriture>>("/api/v1/ecritures?page_size=5").catch(() => null),
        apiGet<MmTransaction[]>("/api/v1/mm/transactions?limit=5").catch(() => []),
      ]);
      setEcritures(e);
      setMmTx(m);
    }
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Tableau de bord</h1>
          <p className="text-sm text-slate-500">Vue d'ensemble de votre activité comptable</p>
        </div>
        <Link href="/ecritures/new">
          <Button size="md">
            <Plus className="h-4 w-4" />
            Nouvelle écriture
          </Button>
        </Link>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <KpiCard
          icon={<BookOpen className="h-5 w-5 text-brand-600" />}
          label="Écritures (total)"
          value={ecritures?.total ?? 0}
        />
        <KpiCard
          icon={<Wallet className="h-5 w-5 text-success-500" />}
          label="Transactions MM"
          value={mmTx.length}
        />
        <KpiCard
          icon={<TrendingUp className="h-5 w-5 text-warning-500" />}
          label="Trésorerie (est.)"
          value={formatXOF(0)}
        />
        <KpiCard
          icon={<Snowflake className="h-5 w-5 text-slate-400" />}
          label="Comptes gelés"
          value={0}
        />
      </div>

      {/* Dernières écritures */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Dernières écritures</CardTitle>
          <Link href="/ecritures" className="text-xs font-medium text-brand-600 hover:underline">
            Voir tout →
          </Link>
        </CardHeader>
        <CardBody className="p-0">
          {!ecritures || ecritures.items.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-slate-500">
              Aucune écriture pour le moment.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-6 py-2 text-left">N° pièce</th>
                  <th className="px-6 py-2 text-left">Date</th>
                  <th className="px-6 py-2 text-left">Libellé</th>
                  <th className="px-6 py-2 text-right">Total</th>
                  <th className="px-6 py-2 text-right">Statut</th>
                </tr>
              </thead>
              <tbody>
                {ecritures.items.map((e) => (
                  <tr key={e.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-6 py-3 font-mono text-xs">{e.numero_piece}</td>
                    <td className="px-6 py-3">{formatDate(e.date_ecriture)}</td>
                    <td className="px-6 py-3 text-slate-700">{e.libelle}</td>
                    <td className="px-6 py-3 text-right font-mono">
                      {formatXOF(e.lignes.reduce((s, l) => s + l.debit_xof, 0))}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <Badge tone={e.statut === "validee" ? "success" : e.statut === "gelee" ? "danger" : "neutral"}>
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

      {/* Derniers flux MM */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Derniers flux Mobile Money</CardTitle>
          <Link href="/mobile-money" className="text-xs font-medium text-brand-600 hover:underline">
            Voir tout →
          </Link>
        </CardHeader>
        <CardBody className="p-0">
          {mmTx.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-slate-500">
              Aucun flux Mobile Money.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-6 py-2 text-left">Provider</th>
                  <th className="px-6 py-2 text-left">Date</th>
                  <th className="px-6 py-2 text-left">Libellé</th>
                  <th className="px-6 py-2 text-right">Montant</th>
                  <th className="px-6 py-2 text-right">Statut</th>
                </tr>
              </thead>
              <tbody>
                {mmTx.map((t) => (
                  <tr key={t.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-6 py-3 font-medium">{providerLabel(t.provider)}</td>
                    <td className="px-6 py-3">{formatDate(t.horodatage)}</td>
                    <td className="px-6 py-3 text-slate-700">{t.libelle ?? t.external_id}</td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${
                        t.sens === "credit" ? "text-success-700" : "text-danger-700"
                      }`}
                    >
                      {t.sens === "credit" ? "+" : "−"}
                      {formatXOF(t.montant_xof)}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <Badge tone={t.statut_rappro === "rapproche" ? "success" : "warning"}>
                        {t.statut_rappro}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
}) {
  return (
    <Card>
      <CardBody className="flex items-center gap-4">
        <div className="rounded-lg bg-slate-50 p-3">{icon}</div>
        <div>
          <p className="text-xs uppercase text-slate-500">{label}</p>
          <p className="text-xl font-bold text-slate-900">{value}</p>
        </div>
      </CardBody>
    </Card>
  );
}
