import { Badge } from "@mantine/core";

interface DocumentStatusBadgeProps {
  status: "pending" | "processing" | "ready" | "failed";
}

export function DocumentStatusBadge({ status }: DocumentStatusBadgeProps) {
  switch (status) {
    case "ready":
      return (
        <Badge color="green" variant="light">
          Ready
        </Badge>
      );
    case "processing":
      return (
        <Badge color="blue" variant="light">
          Processing
        </Badge>
      );
    case "pending":
      return (
        <Badge color="yellow" variant="light">
          Pending
        </Badge>
      );
    case "failed":
      return (
        <Badge color="red" variant="light">
          Failed
        </Badge>
      );
    default:
      return (
        <Badge color="gray" variant="light">
          {status}
        </Badge>
      );
  }
}
