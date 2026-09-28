import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "info" | "success" | "warning" | "danger";

const VARIANTS: Record<Variant, string> = {
  info: "border-brand-100 bg-brand-50 text-brand-900",
  success: "border-success-500/20 bg-success-50 text-success-700",
  warning: "border-warning-500/20 bg-warning-50 text-warning-700",
  danger: "border-danger-500/20 bg-danger-50 text-danger-700",
};

export function Alert({
  variant = "info",
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & { variant?: Variant }) {
  return (
    <div
      role="alert"
      className={cn("rounded-md border px-4 py-3 text-sm", VARIANTS[variant], className)}
      {...props}
    />
  );
}
