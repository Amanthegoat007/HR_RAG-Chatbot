import { Button, Group, Box, Title, ThemeIcon, Stack } from "@mantine/core";
import { FaAngleLeft } from "react-icons/fa6";
import { Link } from "react-router-dom";
 
import type { DashboardHeaderProps } from "./DashboardHeader.types";
 
export default function DashboardHeader({ title, icon }: DashboardHeaderProps) {
  return (
    <Box mb="xl" mt="xs">
      <Group justify="space-between" align="center">
        {/* Left column */}
        <Stack>
          <Button
            component={Link}
            to="/copilot"
            variant="transparent"
            leftSection={<FaAngleLeft />}
            size="s"
            justify="left"
            w="fit-content"
            pl={0}
            c="var(--app-text-primary)"
          >
            Back to Home
          </Button>
 
          <Group align="center">
            <ThemeIcon size={32} radius="md" color="green" variant="filled">
              {icon}
            </ThemeIcon>
 
            <Title order={2} size="h4" fw={700}>
              {title}
            </Title>
          </Group>
        </Stack>
 
        {/* Right button */}
        <Button
          component={Link}
          to="/copilot"
          bg="var(--app-background-dark)"
          leftSection={
            <img
              src="/images/glowOrb.png"
              alt="AI"
              style={{
                width: 18,
                height: 18,
                borderRadius: "50%",
                objectFit: "cover"
              }}
            />
          }
          radius="xl"
          size="md"
          fw={600}
          style={{ transition: "all 0.2s ease" }}
        >
          Ask Ai
        </Button>
      </Group>
    </Box>
  );
}