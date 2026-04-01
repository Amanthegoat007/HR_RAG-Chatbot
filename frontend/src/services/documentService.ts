import { axiosClient } from "./axiosClient";
import axios from "axios";

export type DocumentScope = "library" | "session";
export type DocumentStatus =
  | "pending"
  | "normalizing"
  | "processing"
  | "embedding"
  | "ready"
  | "failed"
  | "needs_review";

export interface DocumentUploadJob {
  document_id: string;
  filename: string;
  file_size_bytes: number;
  status: DocumentStatus;
  job_id: string;
  message: string;
  scope: DocumentScope;
  conversation_id?: string | null;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  original_format: string;
  file_size_bytes: number;
  status: DocumentStatus;
  error_message: string | null;
  uploaded_at: string;
  uploaded_by: string;
  page_count: number | null;
  chunk_count: number;
  processed_at: string | null;
  metadata: Record<string, unknown>;
  scope: DocumentScope;
  conversation_id?: string | null;
}

const normalizeDocument = (raw: any): DocumentInfo => ({
  ...raw,
  scope: raw.scope || raw.metadata?.scope || "library",
  conversation_id:
    raw.conversation_id ||
    raw.metadata?.conversation_id ||
    raw.metadata?.session_id ||
    null,
});

export const documentService = {
  /**
   * Fetch all documents
   */
  async getDocuments(scope: DocumentScope = "library"): Promise<DocumentInfo[]> {
    const res = await axiosClient.get("/api/documents", {
      params: { scope },
    });
    // Backend returns { documents: [...], total: N } — unwrap the envelope
    return (res.data.documents || []).map(normalizeDocument);
  },

  /**
   * Get document status
   */
  async getDocument(documentId: string): Promise<DocumentInfo> {
    const res = await axiosClient.get(`/api/documents/${documentId}`);
    return normalizeDocument(res.data);
  },

  /**
   * Delete a document
   */
  async deleteDocument(documentId: string): Promise<void> {
    try {
      await axiosClient.delete(`/api/documents/${documentId}`);
    } catch (error) {
      // Treat "already gone" as success for idempotent UX.
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        return;
      }
      throw error;
    }
  },

  /**
   * Upload a document
   * Note: The RAG service also handles uploads for the chat directly,
   * but this is for the Admin Document Management page.
   */
  async uploadDocument(
    file: File,
    options: {
      scope: DocumentScope;
      conversationId?: string;
    },
  ): Promise<DocumentUploadJob> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("scope", options.scope);
    if (options.conversationId) {
      formData.append("conversation_id", options.conversationId);
    }

    const res = await axiosClient.post("/api/documents/intake", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return res.data;
  },
};
