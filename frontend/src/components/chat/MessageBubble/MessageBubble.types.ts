import type { PipelineStage, SourceInfo } from "@/types/chat.types";

export interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  loading?: boolean;
  attachment?: { name: string };
  onRefresh?: () => void;
  stages?: PipelineStage[];
  sources?: SourceInfo[];
}
