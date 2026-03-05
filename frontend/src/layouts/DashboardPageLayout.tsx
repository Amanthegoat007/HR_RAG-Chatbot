import { Box, Container, LoadingOverlay } from "@mantine/core";
import HeaderBar from "./components/HeaderBar/HeaderBar";
import DashboardHeader from "./components/DashboardHeader/DashboardHeader";

import type { DashboardPageLayoutProps } from "./DashboardPageLayout.types";

export default function DashboardPageLayout({
  title,
  icon,
  loading,
  children,
}: DashboardPageLayoutProps) {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Box
        h={60}
        px="md"
        style={{
          borderBottom: "1px solid var(--app-border)",
          display: "flex",
          alignItems: "center",
        }}
      >
        <HeaderBar />
      </Box>
      <Container
        fluid
        px="xl"
        py="xs"
        pos="relative"
        style={{
          flex: 1,
          overflowY: "auto",
          width: "100%",
          background: "var(--app-background-module)",
        }}
      >
        <LoadingOverlay visible={loading} />
        <DashboardHeader title={title} icon={icon} />
        {children}
      </Container>
    </Box>
  );
}
