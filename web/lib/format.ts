/**
 * Formatage métier : XOF sans décimales, dates FR, etc.
 */
const XOF_FORMATTER = new Intl.NumberFormat("fr-FR", {
  style: "decimal",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function formatXOF(montant: number | null | undefined): string {
  if (montant == null) return "—";
  return `${XOF_FORMATTER.format(montant)} FCFA`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

export function providerLabel(p: string): string {
  const map: Record<string, string> = {
    wave: "Wave",
    orange_money: "Orange Money",
    mtn_momo: "MTN MoMo",
    moov_money: "Moov Money",
  };
  return map[p] ?? p;
}
