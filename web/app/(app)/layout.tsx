"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { ReadOnlyBanner } from "@/components/subscription/ReadOnlyBanner";
import { apiGet, ApiException } from "@/lib/api-client";
import type { CurrentUser, SubscriptionStatus, Tenant } from "@/lib/types";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [subStatus, setSubStatus] = useState<SubscriptionStatus | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [me, t, s] = await Promise.all([
          apiGet<CurrentUser>("/api/v1/auth/me"),
          apiGet<Tenant>("/api/v1/tenants/me"),
          apiGet<SubscriptionStatus | null>("/api/v1/billing/status").catch(() => null),
        ]);
        setUser(me);
        setTenant(t);
        setSubStatus(s);
        if (me.is_founder) router.push("/cockpit");
      } catch (err) {
        if (err instanceof ApiException && err.status === 401) router.push("/login");
      }
    }
    load();
  }, [router]);

  return (
    <div className="flex h-screen bg-slate-50">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-6">
          <div>
            <h1 className="text-sm font-semibold text-slate-900">
              {tenant?.raison_sociale ?? "Chargement..."}
            </h1>
            <p className="text-xs text-slate-500">
              {tenant?.rccm ?? ""} {tenant?.regime_fiscal ? `· ${tenant.regime_fiscal}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {subStatus && (
              <span className="text-xs text-slate-500">
                {subStatus.jours_restants} jours restants
              </span>
            )}
            <span className="text-sm font-medium text-slate-700">
              {user?.nom_complet ?? ""}
            </span>
          </div>
        </header>

        {subStatus?.force_read_only && <ReadOnlyBanner />}

        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
