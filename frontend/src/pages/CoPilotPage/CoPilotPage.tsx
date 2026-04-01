import { Box } from "@mantine/core";
import { useEffect } from "react";

import HeaderBar from "@/layouts/components/HeaderBar/HeaderBar";
import CopilotShell from "@/components/chat/CopilotShell/CopilotShell";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  fetchConversations,
  fetchMessages,
  setActiveConversation,
  startNewChat,
} from "@/store/slices/chatSlice";
import { useParams } from "react-router-dom";

export default function CoPilotPage() {
  const dispatch = useAppDispatch();
  const { conversationId } = useParams();
  const user = useAppSelector((s) => s.auth.user);
  const chatState = useAppSelector((s) => s.chat);
  const { activeConversationId, conversations, isLoadingMessages } = chatState;
  const selectedConversationId = conversationId ?? activeConversationId;

  const activeConversation = conversations.find(
    (c) => c.id === selectedConversationId,
  );
  const hasSelectedConversation = Boolean(activeConversation);
  const activeMessageCount = activeConversation?.messages.length ?? 0;
  const isHydratingConversation =
    Boolean(conversationId) &&
    (isLoadingMessages ||
      conversationId !== activeConversationId ||
      !hasSelectedConversation);
  const isEmpty =
    !isHydratingConversation &&
    (!selectedConversationId || activeMessageCount === 0);

  // LOAD CONVERSATIONS ON MOUNT
  useEffect(() => {
    if (!user) return;

    void dispatch(fetchConversations());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, dispatch]);

  // SYNC URL TO REDUX
  useEffect(() => {
    if (!user) return;

    if (conversationId) {
      if (conversationId !== activeConversationId) {
        dispatch(setActiveConversation(conversationId));
      }

      if (
        conversationId !== activeConversationId ||
        !hasSelectedConversation ||
        activeMessageCount === 0
      ) {
        void dispatch(fetchMessages(conversationId));
      }
    } else if (activeConversationId) {
      dispatch(startNewChat());
    }
  }, [
    user,
    conversationId,
    activeConversationId,
    hasSelectedConversation,
    activeMessageCount,
    dispatch,
  ]);

  return (
    <Box
      h="100%"
      bg="var(--app-background-secondary)"
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      {/* HEADER SECTION */}
      <Box
        h={60}
        px="md"
        style={{
          background: "transparent",
          borderBottom: "1px solid var(--app-border)",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
        }}
        // We can optimize this further but keeping safe for now as requested "no visual changes" logic is sensitive
      >
        <HeaderBar />
      </Box>

      {/* MAIN BODY SECTION */}
      <Box
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          overflow: "hidden",
          background: "transparent",
        }}
      >
        <Box style={{ flex: 1, minHeight: 0, display: "flex" }}>
          <CopilotShell
            isEmpty={isEmpty}
            isLoadingConversation={isHydratingConversation}
          />
        </Box>
      </Box>
    </Box>
  );
}
