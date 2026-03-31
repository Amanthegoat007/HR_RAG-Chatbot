import type {
  AssistantResponsePayload,
  MessageMetadata,
  PipelineStage,
  SourceInfo,
} from "@/types/chat.types";

export interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  loading?: boolean;
  streaming?: boolean;
  attachment?: { name: string };
  onRefresh?: () => void;
  stages?: PipelineStage[];
  sources?: SourceInfo[];
  metadata?: MessageMetadata;
  responsePayload?: AssistantResponsePayload;
}
