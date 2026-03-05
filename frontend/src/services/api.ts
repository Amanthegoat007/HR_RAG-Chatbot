import { axiosClient } from "./axiosClient";
import type { LoginCredentials } from "@/types/auth.types";

export const authApi = {
  login(credentials: LoginCredentials) {
    return axiosClient.post("/api/auth/login", credentials);
  },

  refreshToken() {
    return axiosClient.post("/api/auth/refresh");
  },

  logout() {
    return axiosClient.post("/api/auth/logout");
  },
};

export const chatApi = {
  async fetchConversations() {
    const res = await axiosClient.get("/api/conversations");
    // Backend returns { conversations: [...] } — unwrap the envelope
    return { data: res.data.conversations || [] };
  },

  async fetchMessages(conversationId: string) {
    const res = await axiosClient.get(`/api/messages/${conversationId}`);
    // Backend returns { messages: [...] } — unwrap the envelope
    return { data: res.data.messages || [] };
  },

  createConversation(title: string) {
    return axiosClient.post("/api/conversations", { title });
  },

  deleteConversation(conversationId: string) {
    return axiosClient.delete(`/api/conversations/${conversationId}`);
  },

  deleteAllConversations() {
    return axiosClient.delete("/api/conversations");
  },

  async sendMessage(
    conversationId: string,
    message: string,
    language?: string,
    signal?: AbortSignal,
  ) {
    const res = await axiosClient.post(
      "/api/messages",
      {
        conversationId,
        message,
        language,
      },
      { signal },
    );

    // Backend returns { userMessage, assistantMessage }
    // Frontend expects { user, assistant }
    return {
      data: {
        user: res.data.userMessage,
        assistant: res.data.assistantMessage,
      },
    };
  },

  stopMessage(conversationId: string) {
    return axiosClient.post("/api/messages/stop", {
      conversation_id: conversationId,
    });
  },

  /**
   * Stream message via SSE — tokens arrive in real time.
   * Uses native fetch (not axios) because axios doesn't support streaming.
   */
  async streamMessage(
    conversationId: string,
    message: string,
    callbacks: {
      onToken: (token: string) => void;
      onMeta: (userMessageId: string) => void;
      onSaved: (assistantMessageId: string) => void;
      onSources: (sources: any[]) => void;
      onStage: (stage: string, label: string, status: string) => void;
      onError: (error: string) => void;
      onDone: (fullText: string) => void;
    },
    signal?: AbortSignal,
  ) {
    const response = await fetch("/api/messages/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ conversationId, message }),
      signal,
    });

    if (!response.ok) {
      throw new Error(`Stream request failed with status ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer (format: "data: {...}\n\n")
      const lines = buffer.split("\n\n");
      buffer = lines.pop() || ""; // Keep incomplete last chunk

      for (const chunk of lines) {
        const dataLine = chunk.trim();
        if (!dataLine.startsWith("data: ")) continue;

        try {
          const data = JSON.parse(dataLine.slice(6));

          switch (data.type) {
            case "token":
              callbacks.onToken(data.content);
              break;
            case "stage":
              callbacks.onStage(data.stage, data.label, data.status);
              break;
            case "meta":
              callbacks.onMeta(data.userMessageId);
              break;
            case "saved":
              callbacks.onSaved(data.assistantMessageId);
              break;
            case "sources":
              callbacks.onSources(data.sources);
              break;
            case "error":
              callbacks.onError(data.content);
              break;
            case "done":
              callbacks.onDone(data.fullText || "");
              break;
          }
        } catch (e) {
          // Skip unparseable events
        }
      }
    }
  },

  deleteMessagesAfter(conversationId: string, messageId: string) {
    return axiosClient.delete(
      `/api/messages/${conversationId}/${messageId}/after`,
    );
  },
};

export const ocrApi = {
  extractText(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return axiosClient.post("/api/ocr/extract-text", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
  },
};

export const transcribeApi = {
  transcribeAudio(blob: Blob, method: string, language?: string) {
    const formData = new FormData();
    formData.append("file", blob, "voice.wav");
    formData.append("method", method);
    if (language) {
      formData.append("language", language);
    }
    return axiosClient.post("/api/speech-service/transcribe", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
  },
};

export const ttsApi = {
  synthesizeText(text: string, language: string = "en") {
    return axiosClient.post(
      "/api/speech-service",
      { text, language },
      {
        responseType: "blob",
      },
    );
  },
};
