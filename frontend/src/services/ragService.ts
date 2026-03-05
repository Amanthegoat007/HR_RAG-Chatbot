import { axiosClient } from "./axiosClient";
import { generateUUID } from "@/utils/uuid";
import { MAX_FILE_UPLOAD_SIZE_MB, MAX_FILE_UPLOAD_SIZE_BYTES } from "@/config/constants";

export const ragService = {
  // Session Management
  createSession: async () => {
    return { data: { id: generateUUID() } };
  },

  getSessions: async () => {
    return axiosClient.get("/api/rag/chat/sessions");
  },

  getHistory: async (sessionId: string) => {
    return axiosClient.get(`/api/rag/chat/${sessionId}/history`);
  },

  // Chat
  sendMessage: async (sessionId: string, message: string) => {
    return axiosClient.post("/api/rag/chat", {
      session_id: sessionId,
      messages: [{ role: "user", content: message }],
    });
  },

  // Files
  uploadFile: async (file: File, sessionId: string) => {
    // --- File Size Check ---
    if (file.size > MAX_FILE_UPLOAD_SIZE_BYTES) {
      throw new Error(`File too large (${(file.size / (1024 * 1024)).toFixed(1)}MB). Maximum allowed: ${MAX_FILE_UPLOAD_SIZE_MB}MB.`);
    }
    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);
    return axiosClient.post("/api/rag/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
  },

  listFiles: async () => {
    return axiosClient.get("/api/rag/list");
  },

  getFileStatus: async (filename: string): Promise<string> => {
    try {
      const response = await axiosClient.get("/api/rag/list");
      const files = response.data as Array<{ name: string; status: string }>;
      const file = files.find((f) => f.name === filename);
      return file?.status || "unknown";
    } catch {
      return "unknown";
    }
  },
  // Session Cleanup - Delete all files/vectors for a session
  deleteSessionFiles: async (sessionId: string) => {
    try {
      const response = await axiosClient.delete(
        `/api/rag/upload/session/${sessionId}/files`,
      );
      console.log(
        `[RAG Cleanup] Deleted session files for: ${sessionId}`,
        response.data,
      );
      return response;
    } catch (error) {
      console.error(
        `[RAG Cleanup] Failed to delete session files for: ${sessionId}`,
        error,
      );
      throw error;
    }
  },
  /**
   * Upload file with OCR support
   * Automatically detects if file needs OCR (PDF/images) and extracts text before uploading to RAG
   * @param file - File to upload (PDF, image, or text document)
   * @param conversationId - Active conversation ID from Redux state
   */
  uploadFileWithOCR: async (file: File, conversationId: string) => {
    // --- File Size Check ---
    if (file.size > MAX_FILE_UPLOAD_SIZE_BYTES) {
      throw new Error(`File too large (${(file.size / (1024 * 1024)).toFixed(1)}MB). Maximum allowed: ${MAX_FILE_UPLOAD_SIZE_MB}MB.`);
    }

    const ocrMimeTypes = [
      // "application/pdf", // Removed to allow direct upload for PDFs (handled by PyPDFLoader in backend)
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // docx
      "application/msword", // doc
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", // xlsx
      "application/vnd.ms-excel", // xls
    ];

    const needsOCR =
      ocrMimeTypes.includes(file.type) || file.type.startsWith("image/");

    if (needsOCR) {
      console.log(`[OCR-RAG] File needs OCR: ${file.name}`);

      // Step 1: Extract text via OCR (backend OCR service)
      const formData = new FormData();
      formData.append("file", file);

      // Use axiosClient for OCR too
      const ocrResponse = await axiosClient.post(
        "/api/ocr/extract-text", // Correct endpoint from ocr.routes.ts
        formData,
        {
          headers: { "Content-Type": "multipart/form-data" },
        },
      );
      const extractedText = ocrResponse.data.text;
      console.log(
        `[OCR-RAG] Extracted ${extractedText.length} characters from ${file.name}`,
      );
      // Step 2: Create text file from extracted content
      const textBlob = new Blob([extractedText], { type: "text/plain" });
      const textFile = new File([textBlob], `${file.name}.extracted.txt`, {
        type: "text/plain",
      });
      // Step 3: Upload to RAG with conversationId as session_id
      const ragFormData = new FormData();
      ragFormData.append("file", textFile);
      ragFormData.append("session_id", conversationId);

      console.log(
        `[OCR-RAG] Uploading extracted text to RAG for conversation: ${conversationId}`,
      );
      return axiosClient.post("/api/rag/upload", ragFormData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    } else {
      // Direct upload for non-OCR files
      console.log(`[OCR-RAG] Direct upload (no OCR needed): ${file.name}`);
      const formData = new FormData();
      formData.append("file", file);
      formData.append("session_id", conversationId);

      return axiosClient.post("/api/rag/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    }
  },
  /**
   * Cleanup all RAG files when conversation is deleted
   * @param conversationId - Conversation ID to cleanup
   */
  cleanupConversationFiles: async (conversationId: string) => {
    try {
      await axiosClient.delete(`/api/rag/upload/session/${conversationId}/files`);
      console.log(`[RAG] Cleaned up files for conversation: ${conversationId}`);
    } catch (error) {
      console.error(`[RAG] Failed to cleanup files:`, error);
      // Don't throw - cleanup failure shouldn't block conversation deletion
    }
  },
  // Verification
  checkHealth: async () => {
    // Backend health, not direct RAG health. RAG health proxy not implemented, or use list as proxy
    return { status: 200, data: { status: "ok" } };
  },
};