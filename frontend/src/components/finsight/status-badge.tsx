import { Badge } from "@/components/ui/badge";
import type { ReportStatus } from "@/lib/schemas";

const MAP: Record<
  ReportStatus,
  { label: string; variant: "success" | "warning" | "danger" | "info" | "default" }
> = {
  completed: { label: "Completed", variant: "success" },
  running: { label: "Running", variant: "info" },
  pending: { label: "Pending", variant: "default" },
  failed: { label: "Failed", variant: "danger" },
  overwritten: { label: "Overwritten", variant: "warning" },
};

export function StatusBadge({ status }: { status: ReportStatus }) {
  const cfg = MAP[status];
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}
