import type { MessageMetadata } from "@/types/chat.types";

export type BackendMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata?: MessageMetadata;
};

export type BackendConversation = {
  id: string;
  title: string;
};
