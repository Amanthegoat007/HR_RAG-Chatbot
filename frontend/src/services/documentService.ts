import { axiosClient } from "./axiosClient";
import axios from "axios";

export interface DocumentInfo {
  id: string;
  filename: string;
  original_format: string;
  file_size_bytes: number;
  status: "pending" | "processing" | "ready" | "failed";
  error_message: string | null;
  uploaded_at: string;
  uploaded_by: string;
  page_count: number | null;
  chunk_count: number;
  processed_at: string | null;
  metadata: Record<string, unknown>;
}

export const documentService = {
  /**
   * Fetch all documents
   */
  async getDocuments(): Promise<DocumentInfo[]> {
    const res = await axiosClient.get("/api/documents");
    // Backend returns { documents: [...], total: N } — unwrap the envelope
    return res.data.documents || [];
  },

  /**
   * Get document status
   */
  async getDocument(documentId: string): Promise<DocumentInfo> {
    const res = await axiosClient.get(`/api/documents/${documentId}`);
    return res.data;
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
  async uploadDocument(file: File): Promise<DocumentInfo> {
    const formData = new FormData();
    formData.append("file", file);

    const res = await axiosClient.post("/api/documents/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return res.data;
  },
};
