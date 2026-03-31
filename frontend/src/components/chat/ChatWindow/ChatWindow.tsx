import { Stack } from "@mantine/core";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import MessageBubble from "../MessageBubble";
import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import {
  streamMessage,
  removeMessagesFromIndex,
  addUserMessage,
} from "@/store/slices/chatSlice";
import { requestManager } from "@/utils/requestManager";
import { chatApi } from "@/services/api";
import { generateUUID } from "@/utils/uuid";
import type { ReasoningMode } from "@/types/chat.types";

import type { ChatWindowProps } from "./ChatWindow.types";
import classes from "./ChatWindow.module.css";

export default function ChatWindow({ scrollContainerRef }: ChatWindowProps) {
  const dispatch = useAppDispatch();
  const { conversations, activeConversationId, sendingConversationIds } =
    useAppSelector((s) => s.chat);
  const { primaryLanguage } = useAppSelector((s) => s.settings);

  const convo = conversations.find((c) => c.id === activeConversationId);

  const isCurrentSending = activeConversationId
    ? sendingConversationIds.includes(activeConversationId)
    : false;

  const lastMessage = convo?.messages[convo.messages.length - 1];
  const previousSnapshotRef = useRef({
    count: 0,
    lastId: "",
  });

  useEffect(() => {
    if (!convo || !scrollContainerRef.current) return;

    const container = scrollContainerRef.current;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    const messageCount = convo.messages.length;
    const lastId = lastMessage?.id ?? "";
    const messageAdded = previousSnapshotRef.current.count !== messageCount;
    const messageChanged = previousSnapshotRef.current.lastId !== lastId;
    const shouldStickToBottom =
      distanceFromBottom < 140 || messageAdded || messageChanged;

    previousSnapshotRef.current = {
      count: messageCount,
      lastId,
    };

    if (!shouldStickToBottom) return;

    window.requestAnimationFrame(() => {
      container.scrollTo({
        top: container.scrollHeight,
        behavior:
          lastMessage?.streaming || lastMessage?.loading ? "auto" : "smooth",
      });
    });
  }, [
    convo?.messages.length,
    lastMessage?.id,
    lastMessage?.content,
    lastMessage?.streaming,
    lastMessage?.loading,
    scrollContainerRef,
  ]);

  const handleRefresh = async (messageIndex: number, reasoningMode: ReasoningMode) => {
    if (!convo || !activeConversationId || isCurrentSending) return;

    // Find the previous user message
    let userMessage = null;
    let userMessageIndex = -1;
    for (let i = messageIndex - 1; i >= 0; i--) {
      if (convo.messages[i].role === "user") {
        userMessage = convo.messages[i];
        userMessageIndex = i;
        break;
      }
    }

    if (!userMessage || userMessageIndex === -1) return;

    try {
      // Capture details before removal
      const {
        content: userContent,
        attachment: userAttachment,
        id: oldUserMessageId,
      } = userMessage;
      const optimisticId = generateUUID();

      // 1. Update UI: Remove old User message (and everything after) and add new Optimistic User message
      // This prevents "duplicate" user messages by replacing the old one with a fresh optimistic one
      // that matches the upcoming sendMessage call.
      dispatch(
        removeMessagesFromIndex({
          conversationId: activeConversationId,
          messageIndex: userMessageIndex,
        }),
      );

      // Add back the user message (optimistic) linked to the new flow
      dispatch(
        addUserMessage({
          id: optimisticId,
          text: userContent,
          attachment: userAttachment,
        }),
      );

      // addAssistantLoading() removed: startStreaming reducer handles loading:true directly

      // 2. Delete messages from backend (starting from the OLD User message)
      // We delete the user message too because sendMessage will create a NEW one.
      await chatApi.deleteMessagesAfter(activeConversationId, oldUserMessageId);

      // 3. Resend the user message (creates new User+Assistant on backend)
      // IMPORTANT: Await the streamMessage thunk so it streams tokens
      const streamPromise = dispatch(
        streamMessage({
          conversationId: activeConversationId,
          message: userContent,
          optimisticId: optimisticId,
          language: primaryLanguage,
          reasoningMode,
        }),
      );

      requestManager.register(activeConversationId, () => {});

      await streamPromise;
    } catch (error: any) {
      // Don't log abort errors as they're expected when user clicks stop
      if (
        error?.message !== "Request cancelled" &&
        error?.message !== "Aborted"
      ) {
        console.error("Failed to regenerate response:", error);
      }
    } finally {
      if (activeConversationId) {
        requestManager.unregister(activeConversationId);
      }
    }
  };

  if (!convo) return null;

  return (
    <motion.div layout className={classes.chatWindow}>
      <Stack gap="md">
      {convo.messages.map((msg, index) => (
        <MessageBubble
          key={msg.id}
          {...msg}
          onRefresh={
            msg.role === "assistant" && !msg.loading
              ? () =>
                  handleRefresh(
                    index,
                    msg.metadata?.requestedReasoningMode ||
                      msg.metadata?.effectiveReasoningMode ||
                      msg.metadata?.reasoningMode ||
                      "fast",
                  )
              : undefined
          }
        />
      ))}
      </Stack>
    </motion.div>
  );
}
