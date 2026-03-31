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
import { useNavigate, useParams } from "react-router-dom";

export default function CoPilotPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const user = useAppSelector((s) => s.auth.user);
  const chatState = useAppSelector((s) => s.chat);
  const { activeConversationId, conversations, isLoadingMessages } = chatState;

  const activeConversation = conversations.find(
    (c) => c.id === activeConversationId,
  );

  // If we are loading messages, we are effectively "not empty" yet (or at least we shouldn't show DraftView)
  // We treat it as empty ONLY if we are NOT loading and truly have no active conversation/messages
  const isEmpty =
    !activeConversationId ||
    (!isLoadingMessages &&
      (!activeConversation || activeConversation.messages.length === 0));

  // LOAD CONVERSATIONS ON MOUNT
  useEffect(() => {
    if (!user) return;

    dispatch(fetchConversations())
      .unwrap()
      .then(() => {
        if (conversationId) {
          dispatch(setActiveConversation(conversationId));
          dispatch(fetchMessages(conversationId));
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, dispatch]);

  // SYNC URL TO REDUX
  useEffect(() => {
    if (conversationId && conversationId !== activeConversationId) {
      dispatch(setActiveConversation(conversationId));
      dispatch(fetchMessages(conversationId));
    } else if (!conversationId && activeConversationId) {
      dispatch(startNewChat());
    }
  }, [conversationId, activeConversationId, dispatch]);

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
          <CopilotShell isEmpty={isEmpty} />
        </Box>
      </Box>
    </Box>
  );
}
