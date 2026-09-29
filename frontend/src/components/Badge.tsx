export type BadgeVariant = "success" | "neutral" | "warning" | "danger" | "info";

const VARIANT_CLASS: Record<BadgeVariant, string> = {
  success: "badge--on",
  neutral: "badge--off",
  warning: "badge--warning",
  danger: "badge--danger",
  info: "badge--info",
};

export function Badge({ variant, children }: { variant: BadgeVariant; children: React.ReactNode }) {
  return <span className={`badge ${VARIANT_CLASS[variant]}`}>{children}</span>;
}
