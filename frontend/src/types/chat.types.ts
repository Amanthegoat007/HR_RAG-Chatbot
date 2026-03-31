export interface PipelineStage {
  stage: string;
  label: string;
  status: string; // "active" | "done"
}

export type ReasoningMode = "fast" | "deep";

export interface SourceInfo {
  filename: string;
  section: string;
  page_number: number;
  document_id: string;
  chunk_index: number;
  score: number;
  text: string;
  heading_path?: string;
  page_start?: number;
  page_end?: number;
}

export interface AssistantTitleBlock {
  type: "title";
  content: string;
}

export interface AssistantSummaryBlock {
  type: "summary";
  content: string;
}

export interface AssistantListBlock {
  type: "list";
  title?: string;
  items: string[];
  ordered?: boolean;
}

export interface AssistantComparisonBlock {
  type: "comparison";
  title?: string;
  rows: Array<{ label: string; content: string }>;
}

export interface AssistantNoteBlock {
  type: "note";
  tone: "neutral" | "warning";
  content: string;
}

export type AssistantResponseBlock =
  | AssistantTitleBlock
  | AssistantSummaryBlock
  | AssistantListBlock
  | AssistantComparisonBlock
  | AssistantNoteBlock;

export interface AssistantResponsePayload {
  version: number;
  questionType?: string;
  reasoningMode?: ReasoningMode;
  blocks: AssistantResponseBlock[];
  sources?: SourceInfo[];
}

export interface MessageMetadata {
  responsePayload?: AssistantResponsePayload;
  sources?: SourceInfo[];
  reasoningMode?: ReasoningMode;
  requestedReasoningMode?: ReasoningMode;
  effectiveReasoningMode?: ReasoningMode;
  questionType?: string;
  answerPath?: string;
  deterministicConfidence?: number;
  deepFallbackApplied?: boolean;
  deepFallbackReason?: "no_visible_tokens" | "empty_answer" | "title_only_answer";
  visibleTokenCount?: number;
  reasoningTokenCount?: number;
  firstVisibleTokenLatencyMs?: number;
  generationLatencyMs?: number;
  turnContext?: {
    activeSubject?: string;
    latestTopicReference?: string;
    recentSummary?: string;
    questionType?: string;
    unresolvedReferences?: string[];
  };
  contextResolution?: {
    resolutionMode?: "direct" | "resolved_follow_up" | "clarify";
    standaloneQuery?: string;
    confidence?: number;
    activeSubject?: string;
    latestTopicReference?: string;
    recentAnswerSummary?: string;
    unresolvedReferences?: string[];
    clarificationQuestion?: string;
    source?: "llm" | "cache" | "fallback";
  };
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: Date | string;
  loading?: boolean;
  streaming?: boolean;
  attachment?: { name: string };
  stages?: PipelineStage[];
  sources?: SourceInfo[];
  metadata?: MessageMetadata;
  responsePayload?: AssistantResponsePayload;
}

export interface ConversationMetadata {
  id: string;
  title: string;
  created_at?: Date | string;
}

export interface Conversation extends ConversationMetadata {
  messages: Message[];
}

export interface MessagePairResponse {
  user: Message;
  assistant: Message;
}

export type ChatState = {
  conversations: Conversation[];
  activeConversationId: string | null;
  draftMessageMode: boolean;
  sendingConversationIds: string[];
  isLoadingConversations: boolean;
  isLoadingMessages: boolean;
  isDeletingConversationId: string | null;
};
