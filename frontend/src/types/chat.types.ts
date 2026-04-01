export interface PipelineStage {
  stage: string;
  label: string;
  status: string; // "active" | "done"
}

export type ReasoningMode = "fast" | "deep";

export type InteractionType =
  | "knowledge_request"
  | "capability"
  | "greeting"
  | "acknowledgement"
  | "closing"
  | "document_request"
  | "clarify"
  | "assistant_capability"
  | "greeting_or_ack"
  | "document"
  | "policy_or_topic";

export type ContextAction =
  | "direct_response"
  | "retrieve"
  | "clarify"
  | "status_only"
  | "resolve";

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
  interactionType?: InteractionType;
  routerConfidence?: number;
  relevanceGuardReason?: string;
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
    interactionType?: InteractionType;
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
    focusType?: "topic" | "policy" | "document" | "none";
    focusId?: string;
    focusLabel?: string;
    action?: ContextAction;
    focusSource?: string;
    interactionType?: InteractionType;
    assistantResponseStyle?: "greeting_warm" | "capability_overview" | "acknowledgement_positive" | "closing_helpful";
  };
  focus?: {
    type?: "topic" | "policy" | "document" | "none";
    id?: string;
    label?: string;
  };
  documentFocus?: {
    documentId?: string;
    displayName?: string;
    resolutionSource?: "llm" | "cache" | "fallback" | "composer" | "explicit_match" | "conversation_memory" | "latest_upload";
    queryMode?: "normal" | "document_scoped" | "status_only";
  };
  trustSummary?: {
    policyTitle?: string;
    policyFamily?: string;
    policyVersion?: string;
    effectiveDate?: string;
    effectiveDateLabel?: string;
    owner?: string;
    jurisdiction?: string;
    freshnessLabel?: string;
    freshnessTone?: "fresh" | "recent" | "stale";
    groundingLabel?: string;
    groundingScore?: number;
    hasConflict?: boolean;
    conflictLabel?: string;
    sourceCount?: number;
  };
  relatedSuggestions?: Array<{
    label: string;
    prompt: string;
  }>;
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
