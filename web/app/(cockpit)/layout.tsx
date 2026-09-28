"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Shield, Users, CreditCard, Snowflake, LogOut } from "lucide-react";
import { apiGet } from "@/lib/api-client";
import type { CurrentUser } from "@/lib/types";
import { logout } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/cockpit", label: "Vue d'ensemble", icon: Shield },
  { href: "/cockpit/tenants", label: "Entreprises", icon: Users },
  { href: "/cockpit/subscriptions", label: "Abonnements", icon: CreditCard },
];

export default function CockpitLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    async function check() {
      try {
        const me = await apiGet<CurrentUser>("/api/v1/auth/me");
        if (!me.is_founder) router.push("/dashboard");
      } catch {
        router.push("/login");
      }
    }
    check();
  }, [router]);

  return (
    <div className="flex h-screen bg-slate-900 text-white">
      <aside className="flex w-64 flex-col border-r border-slate-800 bg-slate-950">
        <div className="flex h-16 items-center border-b border-slate-800 px-6">
          <Shield className="h-5 w-5 text-brand-500" />
          <span className="ml-2 text-sm font-bold">Cockpit</span>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                  active ? "bg-brand-600 text-white" : "text-slate-400 hover:bg-slate-800",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-slate-800 p-3">
          <button
            onClick={logout}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-slate-400 hover:bg-slate-800"
          >
            <LogOut className="h-4 w-4" />
            Déconnexion
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto p-8">{children}</main>
    </div>
  );
}
