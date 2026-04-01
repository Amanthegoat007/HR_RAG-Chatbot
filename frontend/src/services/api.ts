import { axiosClient } from "./axiosClient";
import type { LoginCredentials } from "@/types/auth.types";
import type {
  AssistantResponsePayload,
  MessageMetadata,
} from "@/types/chat.types";
import type {
  BenchmarkBootstrapResponse,
  BenchmarkPreset,
  BenchmarkRunCreatedResponse,
  BenchmarkRunStatusResponse,
} from "@/types/benchmark.types";

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

  async fetchPopularQuestions() {
    const res = await axiosClient.get("/api/conversations/popular-questions");
    return res.data || [];
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
    reasoningMode?: "fast" | "deep",
    activeAttachmentDocumentId?: string,
    signal?: AbortSignal,
  ) {
    const res = await axiosClient.post(
      "/api/messages",
      {
        conversationId,
        message,
        language,
        reasoningMode,
        activeAttachmentDocumentId,
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
    reasoningMode: "fast" | "deep",
    activeAttachmentDocumentId: string | undefined,
    callbacks: {
      onToken: (token: string) => void;
      onMeta: (userMessageId: string) => void;
      onSaved: (assistantMessageId: string) => void;
      onSources: (sources: any[]) => void;
      onStage: (stage: string, label: string, status: string) => void;
      onError: (error: string) => void;
      onDone: (payload: {
        fullText: string;
        responsePayload?: AssistantResponsePayload;
        metadata?: MessageMetadata;
      }) => void;
    },
    signal?: AbortSignal,
  ) {
    const response = await fetch("/api/messages/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        conversationId,
        message,
        reasoningMode,
        activeAttachmentDocumentId,
      }),
      signal,
    });

    if (!response.ok) {
      throw new Error(`Stream request failed with status ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";
    let sawDone = false;
    let sawToken = false;

    const processEventBlock = (chunk: string) => {
      const dataLine = chunk.trim();
      if (!dataLine.startsWith("data: ")) return;

      try {
        const data = JSON.parse(dataLine.slice(6));

        switch (data.type) {
          case "token":
            sawToken = true;
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
            sawDone = true;
            callbacks.onDone({
              fullText: data.fullText || "",
              responsePayload: data.responsePayload,
              metadata: data.metadata,
            });
            break;
        }
      } catch (e) {
        // Skip unparseable events
      }
    };

    const drainBuffer = (flushRemainder = false) => {
      const chunks = buffer.split("\n\n");
      if (!flushRemainder) {
        buffer = chunks.pop() || "";
      } else {
        buffer = "";
      }

      for (const chunk of chunks) {
        processEventBlock(chunk);
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        drainBuffer(true);
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      drainBuffer(false);
    }

    if (!sawDone) {
      if (!sawToken) {
        callbacks.onError("Something went wrong. Please try again.");
      }
      callbacks.onDone({ fullText: "" });
    }
  },

  deleteMessagesAfter(conversationId: string, messageId: string) {
    return axiosClient.delete(
      `/api/messages/${conversationId}/${messageId}/after`,
    );
  },
};

export const benchmarkApi = {
  async fetchBootstrap() {
    const res = await axiosClient.get<BenchmarkBootstrapResponse>("/api/benchmark");
    return res.data;
  },

  async runBenchmark(preset: BenchmarkPreset, concurrency?: number) {
    const res = await axiosClient.post<BenchmarkRunCreatedResponse>(
      "/api/benchmark/run",
      { preset, concurrency },
    );
    return res.data;
  },

  async fetchRun(jobId: string) {
    const res = await axiosClient.get<BenchmarkRunStatusResponse>(
      `/api/benchmark/runs/${jobId}`,
    );
    return res.data;
  },
};
