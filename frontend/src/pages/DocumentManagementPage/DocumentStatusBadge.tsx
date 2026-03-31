import { Badge } from "@mantine/core";

interface DocumentStatusBadgeProps {
  status: string;
}

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  ready: { color: "green", label: "Ready" },
  processing: { color: "blue", label: "Processing" },
  pending: { color: "yellow", label: "Pending" },
  normalizing: { color: "cyan", label: "Normalizing" },
  embedding: { color: "indigo", label: "Embedding" },
  needs_review: { color: "orange", label: "Review" },
  failed: { color: "red", label: "Failed" },
};

export function DocumentStatusBadge({ status }: DocumentStatusBadgeProps) {
  const config = STATUS_CONFIG[status] || { color: "gray", label: status };

  return (
    <Badge color={config.color} variant="light">
      {config.label}
    </Badge>
  );
}
