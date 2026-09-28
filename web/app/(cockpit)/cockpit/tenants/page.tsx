"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import type { Tenant } from "@/lib/types";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/format";

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);

  useEffect(() => {
    apiGet<Tenant[]>("/api/v1/cockpit/tenants").then(setTenants).catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Entreprises</h1>
        <p className="text-sm text-slate-400">{tenants.length} entreprises clientes</p>
      </div>

      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="border-slate-800">
          <CardTitle className="text-white">Liste</CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-800 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-6 py-3 text-left">Slug</th>
                <th className="px-6 py-3 text-left">Raison sociale</th>
                <th className="px-6 py-3 text-left">Pays</th>
                <th className="px-6 py-3 text-left">Régime</th>
                <th className="px-6 py-3 text-left">Créée le</th>
                <th className="px-6 py-3 text-right">Statut</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr key={t.id} className="border-b border-slate-800 last:border-0">
                  <td className="px-6 py-3 font-mono text-xs">{t.slug}</td>
                  <td className="px-6 py-3">{t.raison_sociale}</td>
                  <td className="px-6 py-3">{t.pays}</td>
                  <td className="px-6 py-3">{t.regime_fiscal ?? "—"}</td>
                  <td className="px-6 py-3">{formatDate(t.created_at)}</td>
                  <td className="px-6 py-3 text-right">
                    <Badge tone={t.statut === "actif" ? "success" : t.statut === "gele" ? "danger" : "neutral"}>
                      {t.statut}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </div>
  );
}
