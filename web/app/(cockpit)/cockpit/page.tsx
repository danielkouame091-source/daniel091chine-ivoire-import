"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";

interface Stats {
  tenants: number;
  users: number;
  ecritures: number;
  freeze_actifs: number;
}

export default function CockpitHome() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    apiGet<Stats>("/api/v1/cockpit/stats").then(setStats).catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Vue d'ensemble</h1>
        <p className="text-sm text-slate-400">Pilotage global de la plateforme</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <StatCard label="Entreprises" value={stats?.tenants ?? 0} />
        <StatCard label="Utilisateurs" value={stats?.users ?? 0} />
        <StatCard label="Écritures" value={stats?.ecritures ?? 0} />
        <StatCard label="Gels actifs" value={stats?.freeze_actifs ?? 0} accent />
      </div>

      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="border-slate-800">
          <CardTitle className="text-white">Actions rapides</CardTitle>
        </CardHeader>
        <CardBody className="text-sm text-slate-300">
          <ul className="space-y-2">
            <li>→ Consulter la liste des entreprises</li>
            <li>→ Vérifier les abonnements expirant sous 7 jours</li>
            <li>→ Auditer l'intégrité des chaînes d'audit</li>
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className={`rounded-lg border p-6 ${accent ? "border-danger-500/50 bg-danger-500/10" : "border-slate-800 bg-slate-900"}`}>
      <p className="text-xs uppercase text-slate-400">{label}</p>
      <p className="mt-2 text-3xl font-bold">{value}</p>
    </div>
  );
}
