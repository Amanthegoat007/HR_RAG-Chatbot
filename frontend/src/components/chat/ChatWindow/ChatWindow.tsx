import { Stack } from "@mantine/core";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import MessageBubble from "../MessageBubble";
import React, { useEffect } from "react";
import {
  streamMessage,
  addAssistantLoading,
  removeMessagesFromIndex,
  addUserMessage,
} from "@/store/slices/chatSlice";
import { requestManager } from "@/utils/requestManager";
import { chatApi } from "@/services/api";
import { generateUUID } from "@/utils/uuid";

import type { ChatWindowProps } from "./ChatWindow.types";

export default function ChatWindow({ scrollContainerRef }: ChatWindowProps) {
  const dispatch = useAppDispatch();
  const { conversations, activeConversationId, sendingConversationIds } =
    useAppSelector((s) => s.chat);
  const { primaryLanguage } = useAppSelector((s) => s.settings);

  const convo = conversations.find((c) => c.id === activeConversationId);

  const isCurrentSending = activeConversationId
    ? sendingConversationIds.includes(activeConversationId)
    : false;

  // Auto-scroll when messages change (new messages, streaming tokens, etc.)
  const lastMessage = convo?.messages[convo.messages.length - 1];
  useEffect(() => {
    if (!convo || !scrollContainerRef.current) return;

    // Use scrollTo on the container instead of scrollIntoView on an element
    // This prevents the parent page from scrolling down
    scrollContainerRef.current.scrollTo({
      top: scrollContainerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [convo, scrollContainerRef, lastMessage?.content]);

  const handleRefresh = async (messageIndex: number) => {
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
    <Stack
      style={{
        margin: " 0 auto",
        padding: "1rem 0",
      }}
    >
      {convo.messages.map((msg, index) => (
        <MessageBubble
          key={msg.id}
          {...msg}
          onRefresh={
            msg.role === "assistant" && !msg.loading
              ? () => handleRefresh(index)
              : undefined
          }
        />
      ))}
    </Stack>
  );
}
