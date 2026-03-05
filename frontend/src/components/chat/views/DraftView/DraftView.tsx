import { Box } from "@mantine/core";
import DashboardHero from "@/components/chat/dashboard/DashboardHero";
import ChatInput from "@/components/chat/ChatInput";
import QuickAccessCategories from "@/components/chat/dashboard/QuickAccessCategories";

export default function DraftView() {
  return (
    <Box w="100%" mih="100%" display="flex" style={{ flexDirection: "column" }}>
      <Box style={{ flex: 1 }}>
        <DashboardHero />
      </Box>
      <Box w="100%" maw={900} mx="auto" mb="2rem">
        <ChatInput isHeroMode />
      </Box>
      <Box w="100%" maw={900} mx="auto" mb="2rem">
        <QuickAccessCategories />
      </Box>
    </Box>
  );
}
