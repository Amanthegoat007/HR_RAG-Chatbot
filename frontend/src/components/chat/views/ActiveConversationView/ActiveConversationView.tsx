import { Box } from "@mantine/core";
import { useRef } from "react";
import ChatWindow from "@/components/chat/ChatWindow";
import ChatInput from "@/components/chat/ChatInput";
import QuickAccessCategories from "@/components/chat/dashboard/QuickAccessCategories";

export default function ActiveConversationView() {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  return (
    <Box display="flex" maw="80%" mx="auto" style={{ flexDirection: "column" }}>
      {/* Primary View: Chat Window + Input (90% height) */}
      <Box display="flex" style={{ flexDirection: "column", overflow: "hidden" }} >
        <Box display="flex" style={{ flexDirection: "column", height: "70vh", overflow: "hidden" }} >
          {/* Chat Content expands to fill available space */}
          <Box
            ref={scrollContainerRef}
            maw="100%"
            style={{ flex: 1, overflowY: "auto" }}
          >
            <ChatWindow scrollContainerRef={scrollContainerRef} />
          </Box>
          {/* Input Area */}
        </Box>
        <Box
          // p="md"
          maw="100%"
          display="flex"
          style={{
            flexDirection: "column",
            alignItems: "center",
            background: "transparent",
          }}
        >
          <Box maw={900} w="100%">
            <ChatInput />
          </Box>
        </Box>
      </Box>
      {/* Below the Fold: Action Categories (Scrollable and Hidden by default) */}
      <Box py="xl" display="flex" style={{ justifyContent: "center" }}>
        <QuickAccessCategories />
      </Box>
    </Box>
  );
}
