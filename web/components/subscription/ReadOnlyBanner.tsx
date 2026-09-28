"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";

export function ReadOnlyBanner() {
  return (
    <div className="flex items-center gap-3 border-b border-warning-500/20 bg-warning-50 px-6 py-3 text-sm text-warning-700">
      <AlertTriangle className="h-4 w-4 flex-shrink-0" />
      <div className="flex-1">
        <strong>Abonnement expiré.</strong> Votre compte est en lecture seule — vous ne pouvez
        plus créer ni modifier d'écritures.
      </div>
      <Link
        href="/billing"
        className="rounded-md bg-warning-500 px-3 py-1 text-xs font-semibold text-white hover:bg-warning-700"
      >
        Renouveler
      </Link>
    </div>
  );
}
