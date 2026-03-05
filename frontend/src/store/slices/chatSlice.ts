import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { chatApi } from "@/services/api";
import { logout } from "./authSlice";
import type { RootState } from "..";
import type { ChatState, Message, Conversation } from "@/types/chat.types";

import type { BackendMessage, BackendConversation } from "./chatSlice.types";
import { generateUUID } from "@/utils/uuid";
import type { AppDispatch } from "..";

const initialState: ChatState = {
  conversations: [],
  activeConversationId: null,
  draftMessageMode: true,
  sendingConversationIds: [],
  isLoadingConversations: false,
  isLoadingMessages: false,
  isDeletingConversationId: null,
};

export const fetchConversations = createAsyncThunk<
  BackendConversation[],
  void,
  { state: RootState }
>("chat/fetchConversations", async (_, { getState, rejectWithValue }) => {
  if (!getState().auth.isAuthenticated) {
    return rejectWithValue("Not authenticated");
  }

  const { data } = await chatApi.fetchConversations();
  return data;
});

export const fetchMessages = createAsyncThunk<
  { conversationId: string; messages: BackendMessage[] },
  string,
  { state: RootState }
>(
  "chat/fetchMessages",
  async (conversationId, { getState, rejectWithValue }) => {
    if (!getState().auth.isAuthenticated) {
      return rejectWithValue("Not authenticated");
    }

    const { data } = await chatApi.fetchMessages(conversationId);
    return { conversationId, messages: data };
  },
);

export const createConversation = createAsyncThunk<
  BackendConversation,
  string,
  { state: RootState }
>("chat/createConversation", async (title, { getState, rejectWithValue }) => {
  if (!getState().auth.isAuthenticated) {
    return rejectWithValue("Not authenticated");
  }

  const { data } = await chatApi.createConversation(title);

  return data;
});

export const deleteConversation = createAsyncThunk<
  string,
  string,
  { state: RootState }
>(
  "chat/deleteConversation",
  async (conversationId, { getState, rejectWithValue }) => {
    const state = getState();
    if (!state.auth.isAuthenticated) {
      return rejectWithValue("Not authenticated");
    }

    await chatApi.deleteConversation(conversationId);

    // Cleanup RAG files for this conversation
    try {
      const { ragService } = await import("@/services/ragService");
      await ragService.cleanupConversationFiles(conversationId);
    } catch (error) {
      console.error("[RAG Cleanup] Failed to cleanup files:", error);
      // Don't fail the whole deletion if RAG cleanup fails
    }

    return conversationId;
  },
);

export const deleteAllConversations = createAsyncThunk<
  void,
  void,
  { state: RootState }
>("chat/deleteAllConversations", async (_, { getState, rejectWithValue }) => {
  if (!getState().auth.isAuthenticated) {
    return rejectWithValue("Not authenticated");
  }

  await chatApi.deleteAllConversations();
});

export const sendMessage = createAsyncThunk<
  {
    conversationId: string;
    user: BackendMessage;
    assistant: BackendMessage;
    optimisticId: string;
  },
  {
    conversationId: string;
    message: string;
    optimisticId: string;
    language?: string;
  },
  { state: RootState }
>(
  "chat/sendMessage",
  async (payload, { getState, rejectWithValue, signal }) => {
    if (!getState().auth.isAuthenticated) {
      return rejectWithValue("Not authenticated");
    }

    try {
      const { data } = await chatApi.sendMessage(
        payload.conversationId,
        payload.message,
        payload.language,
        signal,
      );

      return {
        conversationId: payload.conversationId,
        user: data.user,
        assistant: data.assistant,
        optimisticId: payload.optimisticId,
      };
    } catch (error: unknown) {
      const err = error as Error & { name?: string; code?: string };
      if (
        err?.name === "CanceledError" ||
        err?.name === "AbortError" ||
        err?.code === "ERR_CANCELED"
      ) {
        return rejectWithValue("Request cancelled");
      }

      throw error;
    }
  },
);

export const stopMessage = createAsyncThunk<void, string, { state: RootState }>(
  "chat/stopMessage",
  async (conversationId, { getState, rejectWithValue }) => {
    if (!getState().auth.isAuthenticated) {
      return rejectWithValue("Not authenticated");
    }

    try {
      await chatApi.stopMessage(conversationId);
    } catch (error) {
      console.error("Failed to notify backend about stop:", error);
    }
  },
);

/**
 * Stream a message via SSE — dispatches tokens to the store in real-time.
 * This is NOT a createAsyncThunk because we need to dispatch intermediate actions.
 */
export const streamMessage =
  (payload: {
    conversationId: string;
    message: string;
    optimisticId: string;
    language?: string;
  }) =>
  async (dispatch: AppDispatch, getState: () => RootState) => {
    if (!getState().auth.isAuthenticated) return;

    const abortController = new AbortController();
    const streamingMsgId = generateUUID();

    // Mark conversation as sending
    dispatch(chatSlice.actions._startSending(payload.conversationId));
    // Add the streaming assistant message (replaces loading bubble)
    dispatch(
      chatSlice.actions.startStreaming({
        conversationId: payload.conversationId,
        streamingMessageId: streamingMsgId,
      }),
    );

    try {
      await chatApi.streamMessage(
        payload.conversationId,
        payload.message,
        {
          onToken: (token: string) => {
            dispatch(
              chatSlice.actions.appendStreamToken({
                conversationId: payload.conversationId,
                token,
              }),
            );
          },
          onMeta: (userMessageId: string) => {
            // Update the optimistic user message ID with the real DB ID
            dispatch(
              chatSlice.actions._updateUserMessageId({
                conversationId: payload.conversationId,
                optimisticId: payload.optimisticId,
                realId: userMessageId,
              }),
            );
          },
          onSaved: (assistantMessageId: string) => {
            // Update the streaming message ID with the real DB ID
            dispatch(
              chatSlice.actions._updateAssistantMessageId({
                conversationId: payload.conversationId,
                streamingMessageId: streamingMsgId,
                realId: assistantMessageId,
              }),
            );
          },
          onSources: (sources: any[]) => {
            dispatch(
              chatSlice.actions.setSources({
                conversationId: payload.conversationId,
                sources,
              }),
            );
          },
          onStage: (stage: string, label: string, status: string) => {
            dispatch(
              chatSlice.actions.updateStage({
                conversationId: payload.conversationId,
                stage,
                label,
                status,
              }),
            );
          },
          onError: (error: string) => {
            dispatch(
              chatSlice.actions.appendStreamToken({
                conversationId: payload.conversationId,
                token: error,
              }),
            );
          },
          onDone: (_fullText: string) => {
            dispatch(
              chatSlice.actions.finalizeStream({
                conversationId: payload.conversationId,
              }),
            );
          },
        },
        abortController.signal,
      );
    } catch (error: any) {
      if (error?.name === "AbortError") {
        dispatch(
          chatSlice.actions.finalizeStream({
            conversationId: payload.conversationId,
          }),
        );
        return;
      }
      // Show error in the streaming message
      dispatch(
        chatSlice.actions.appendStreamToken({
          conversationId: payload.conversationId,
          token: "Something went wrong. Please try again.",
        }),
      );
      dispatch(
        chatSlice.actions.finalizeStream({
          conversationId: payload.conversationId,
        }),
      );
    } finally {
      dispatch(chatSlice.actions._stopSending(payload.conversationId));
    }

    return abortController;
  };

const chatSlice = createSlice({
  name: "chat",
  initialState,
  reducers: {
    startNewChat(state) {
      state.activeConversationId = null;
      state.draftMessageMode = true;
    },

    setActiveConversation(state, action) {
      state.activeConversationId = action.payload;
      state.draftMessageMode = false;
    },

    addUserMessage(
      state,
      action: {
        payload:
          | string
          | { id?: string; text: string; attachment?: { name: string } };
      },
    ) {
      if (!state.activeConversationId) return;

      const convo = state.conversations.find(
        (c) => c.id === state.activeConversationId,
      );
      if (!convo) return;

      if (typeof action.payload === "string") {
        convo.messages.push({
          id: generateUUID(),
          role: "user",
          content: action.payload,
        });
      } else {
        convo.messages.push({
          id: action.payload.id || generateUUID(),
          role: "user",
          content: action.payload.text,
          attachment: action.payload.attachment,
        });
      }
    },

    addAssistantLoading(state) {
      if (!state.activeConversationId) return;

      const convo = state.conversations.find(
        (c) => c.id === state.activeConversationId,
      );
      if (!convo) return;

      convo.messages.push({
        id: generateUUID(),
        role: "assistant",
        content: "",
        loading: true,
      });
    },

    removeMessagesFromIndex(
      state,
      action: { payload: { conversationId: string; messageIndex: number } },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;

      // Remove all messages from the specified index onwards
      convo.messages = convo.messages.slice(0, action.payload.messageIndex);
    },

    // ---- Streaming reducers ----

    _startSending(state, action: { payload: string }) {
      if (!state.sendingConversationIds.includes(action.payload)) {
        state.sendingConversationIds.push(action.payload);
      }
    },

    _stopSending(state, action: { payload: string }) {
      state.sendingConversationIds = state.sendingConversationIds.filter(
        (id) => id !== action.payload,
      );
    },

    startStreaming(
      state,
      action: {
        payload: { conversationId: string; streamingMessageId: string };
      },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      // Remove any existing loading bubble
      convo.messages = convo.messages.filter(
        (m) => !(m.role === "assistant" && m.loading),
      );
      // Add streaming assistant message — starts in loading state (shows dots)
      // loading:true will be cleared by appendStreamToken when first token arrives
      convo.messages.push({
        id: action.payload.streamingMessageId,
        role: "assistant",
        content: "",
        streaming: true,
        loading: true,
        stages: [],
        sources: [],
      });
    },

    appendStreamToken(
      state,
      action: { payload: { conversationId: string; token: string } },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      const msg = convo.messages.find((m) => m.streaming);
      if (msg) {
        // Clear loading flag on first token so dots disappear and text starts
        if (msg.loading) msg.loading = false;
        msg.content += action.payload.token;
      }
    },

    finalizeStream(state, action: { payload: { conversationId: string } }) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      const msg = convo.messages.find((m) => m.streaming);
      if (msg) {
        msg.streaming = false;
      }
    },

    updateStage(
      state,
      action: {
        payload: {
          conversationId: string;
          stage: string;
          label: string;
          status: string;
        };
      },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      const msg = convo.messages.find((m) => m.streaming || m.loading);
      if (!msg) return;
      if (!msg.stages) msg.stages = [];
      const existing = msg.stages.find(
        (s: any) => s.stage === action.payload.stage,
      );
      if (existing) {
        existing.label = action.payload.label;
        existing.status = action.payload.status;
      } else {
        msg.stages.push({
          stage: action.payload.stage,
          label: action.payload.label,
          status: action.payload.status,
        });
      }
    },

    setSources(
      state,
      action: {
        payload: { conversationId: string; sources: any[] };
      },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      const msg = convo.messages.find((m) => m.streaming);
      if (msg) {
        msg.sources = action.payload.sources;
      }
    },

    _updateUserMessageId(
      state,
      action: {
        payload: {
          conversationId: string;
          optimisticId: string;
          realId: string;
        };
      },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      const msg = convo.messages.find(
        (m) => m.id === action.payload.optimisticId,
      );
      if (msg) msg.id = action.payload.realId;
    },

    _updateAssistantMessageId(
      state,
      action: {
        payload: {
          conversationId: string;
          streamingMessageId: string;
          realId: string;
        };
      },
    ) {
      const convo = state.conversations.find(
        (c) => c.id === action.payload.conversationId,
      );
      if (!convo) return;
      const msg = convo.messages.find(
        (m) => m.id === action.payload.streamingMessageId,
      );
      if (msg) msg.id = action.payload.realId;
    },
  },

  extraReducers: (builder) => {
    builder
      /* ===== SEND MESSAGE ===== */
      .addCase(sendMessage.pending, (state, action) => {
        state.sendingConversationIds.push(action.meta.arg.conversationId);
      })
      .addCase(sendMessage.fulfilled, (state, action) => {
        state.sendingConversationIds = state.sendingConversationIds.filter(
          (id) => id !== action.payload.conversationId,
        );
        const convo = state.conversations.find(
          (c) => c.id === action.payload.conversationId,
        );
        if (!convo) return;

        // Remove loading bubble
        convo.messages = convo.messages.filter(
          (m) => !(m.role === "assistant" && m.loading),
        );

        // Replace optimistic user message ID using the unique optimisticId
        const optUser = convo.messages.find(
          (m) => m.id === action.payload.optimisticId,
        );
        if (optUser) {
          optUser.id = action.payload.user.id;
        }

        // Add assistant reply
        const assistantText = action.payload.assistant.content;
        convo.messages.push({
          id: action.payload.assistant.id,
          role: "assistant",
          content: assistantText,
        });
      })
      .addCase(sendMessage.rejected, (state, action) => {
        const convoId = action.meta.arg.conversationId;

        state.sendingConversationIds = state.sendingConversationIds.filter(
          (id) => id !== convoId,
        );

        const convo = state.conversations.find((c) => c.id === convoId);
        if (!convo) return;

        // Remove loading bubble
        convo.messages = convo.messages.filter(
          (m) => !(m.role === "assistant" && m.loading),
        );

        //  USER STOPPED GENERATION
        if (
          action.payload === "Request cancelled" ||
          action.error.name === "AbortError" ||
          action.meta.aborted
        ) {
          convo.messages.push({
            id: generateUUID(),
            role: "assistant",
            content: "Response generation stopped.",
          });
          return;
        }

        // Real error
        convo.messages.push({
          id: generateUUID(),
          role: "assistant",
          content: "Something went wrong. Please try again.",
        });
      })

      /* ===== FETCH CONVERSATIONS ===== */
      .addCase(fetchConversations.pending, (state) => {
        state.isLoadingConversations = true;
      })
      .addCase(fetchConversations.fulfilled, (state, action) => {
        state.isLoadingConversations = false;

        // Create a map of existing conversations to preserve their messages
        const existingConvosMap = new Map(
          state.conversations.map((c) => [c.id, c]),
        );

        state.conversations = action.payload.map((c) => {
          const existing = existingConvosMap.get(c.id);
          return {
            id: c.id,
            title: c.title,
            // Preserve messages if they exist locally (e.g. optimistic updates), otherwise empty
            messages: existing ? existing.messages : [],
          };
        });

        // Initializing from localStorage is now handled in getInitialActiveConversationId
        // but we verify if the saved ID still exists in the fetched list
        if (state.activeConversationId) {
          const exists = state.conversations.some(
            (c) => c.id === state.activeConversationId,
          );
          if (!exists) {
            state.activeConversationId = null;
            state.draftMessageMode = true;
          }
        }
      })
      .addCase(fetchConversations.rejected, (state) => {
        state.isLoadingConversations = false;
        return initialState;
      })

      /* ===== FETCH MESSAGES ===== */
      .addCase(fetchMessages.pending, (state) => {
        state.isLoadingMessages = true;
      })
      .addCase(fetchMessages.fulfilled, (state, action) => {
        state.isLoadingMessages = false;
        const convo = state.conversations.find(
          (c) => c.id === action.payload.conversationId,
        );
        if (!convo) return;

        const newMessages: Message[] = action.payload.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
        }));

        // Preserve optimistic/loading state if we are currently sending
        if (
          state.sendingConversationIds.includes(action.payload.conversationId)
        ) {
          const oldMessages = convo.messages;
          const lastOld = oldMessages[oldMessages.length - 1];

          // If the last message was a loading bubble, keep it
          if (lastOld?.loading) {
            const secondLastOld = oldMessages[oldMessages.length - 2];
            const lastNew = newMessages[newMessages.length - 1];

            // If we have an optimistic user message before the loading bubble
            if (secondLastOld?.role === "user") {
              // Check if it's already in the new list (by content matching the last item)
              const isSynced =
                lastNew?.role === "user" &&
                lastNew.content === secondLastOld.content;

              if (!isSynced) {
                newMessages.push(secondLastOld);
              }
            }

            newMessages.push(lastOld);
          }
        }

        convo.messages = newMessages;
      })
      .addCase(fetchMessages.rejected, (state) => {
        state.isLoadingMessages = false;
      })

      /* ===== CREATE ===== */
      .addCase(createConversation.fulfilled, (state, action) => {
        state.conversations.unshift({
          id: action.payload.id,
          title: action.payload.title,
          messages: [],
        });

        state.activeConversationId = action.payload.id;
        state.draftMessageMode = false;
      })

      /* ===== DELETE ===== */
      .addCase(deleteConversation.pending, (state, action) => {
        state.isDeletingConversationId = action.meta.arg;
      })
      .addCase(deleteConversation.fulfilled, (state, action) => {
        state.isDeletingConversationId = null;
        const wasActive = state.activeConversationId === action.payload;
        state.conversations = state.conversations.filter(
          (c) => c.id !== action.payload,
        );

        if (state.conversations.length === 0) {
          state.activeConversationId = null;
          state.draftMessageMode = true;
        } else if (wasActive) {
          // If we deleted the active conversation, it naturally defaults to 'New Chat'
          // unless logic elsewhere forces selection. For now, let's default to New Chat.
          state.activeConversationId = null;
          state.draftMessageMode = true;
        }
      })
      .addCase(deleteConversation.rejected, (state) => {
        state.isDeletingConversationId = null;
      })

      /* ===== DELETE ALL ===== */
      .addCase(deleteAllConversations.fulfilled, (state) => {
        state.conversations = [];
        state.activeConversationId = null;
        state.draftMessageMode = true;
        state.sendingConversationIds = [];
        state.isLoadingConversations = false;
        state.isDeletingConversationId = null;
      })

      /* ===== LOGOUT RESET ===== */
      .addCase(logout, () => initialState);
  },
});

export const {
  startNewChat,
  setActiveConversation,
  addUserMessage,
  addAssistantLoading,
  removeMessagesFromIndex,
} = chatSlice.actions;

export default chatSlice.reducer;
