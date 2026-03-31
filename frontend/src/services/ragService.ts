import { axiosClient } from "./axiosClient";

export const ragService = {
  async cleanupConversationFiles(conversationId: string) {
    try {
      await axiosClient.delete(`/api/documents/session/${conversationId}/files`);
    } catch (error) {
      console.error("[RAG Cleanup] Failed to cleanup files:", error);
    }
  },
};
