export interface PipelineStage {
  stage: string;
  label: string;
  status: string; // "active" | "done"
}

export interface SourceInfo {
  filename: string;
  section: string;
  page_number: number;
  document_id: string;
  chunk_index: number;
  score: number;
  text: string;
  heading_path?: string;
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
