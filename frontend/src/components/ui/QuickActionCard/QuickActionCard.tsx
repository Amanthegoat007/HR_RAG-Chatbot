import { useState } from "react";
import {
  Box,
  Paper,
  Text,
  ThemeIcon,
  Group,
  UnstyledButton,
  useComputedColorScheme,
} from "@mantine/core";
import { TbArrowUpRight, TbLayoutDashboard } from "react-icons/tb";
import { IconType } from "react-icons";

import { QuickActionCardProps } from "./QuickActionCard.types";

export default function QuickActionCard({
  title,
  description,
  icon: Icon,
  onClick,
}: QuickActionCardProps) {
  const ActualIcon = Icon || TbLayoutDashboard;
  const computedColorScheme = useComputedColorScheme("light");
  const [isHovered, setIsHovered] = useState(false);

  return (
    <UnstyledButton onClick={onClick} style={{ width: "100%", height: "100%" }}>
      <Paper
        p="md"
        radius="lg"
        h={150}
        style={{
          backgroundColor: "var(--app-surface-hover)",
          display: "flex",
          flexDirection: "column",
          transition: "all 0.2s ease",
          border: "1px solid transparent",
          cursor: "pointer",
        }}
        onMouseEnter={(e) => {
          setIsHovered(true);
          e.currentTarget.style.borderColor = "var(--app-border-hover)";
          e.currentTarget.style.transform = "translateY(-4px)";
          e.currentTarget.style.boxShadow = "var(--app-shadow-lg)";
        }}
        onMouseLeave={(e) => {
          setIsHovered(false);
          e.currentTarget.style.borderColor = "transparent";
          e.currentTarget.style.transform = "translateY(0)";
          e.currentTarget.style.boxShadow = "none";
        }}
      >
        {/* Top Section */}
        <Group justify="space-between" align="flex-start" mb="xs">
          <Box
            style={{
              width: 36,
              height: 36,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <ActualIcon
              size={20}
              style={{ color: "var(--app-text-primary)" }}
            />
          </Box>

          <ThemeIcon
            radius="xl"
            size="sm"
            style={{
              backgroundColor: isHovered
                ? "var(--app-background)"
                : "var(--app-text-primary)",
              color: isHovered ? "var(--app-accent-primary)" : "var(--app-background)",
              border: isHovered
                ? "1px solid var(--app-accent-primary)"
                : "1px solid transparent",
              transition: "all 0.2s ease",
            }}
          >
            <TbArrowUpRight size={14} />
          </ThemeIcon>
        </Group>

        {/* Text Section */}
        <Box mb="auto">
          <Text
            fw={700}
            size="md"
            mb={6}
            lineClamp={1}
            style={{ color: "var(--app-text-primary)" }}
          >
            {title}
          </Text>

          <Text
            size="xs"
            lineClamp={2}
            style={{ lineHeight: 1.5, color: "var(--app-text-secondary)" }}
          >
            {description}
          </Text>
        </Box>

        <Box h={8} />
      </Paper>
    </UnstyledButton>
  );
}
