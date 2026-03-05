import { Box, Container, Stack, Text, Title } from "@mantine/core";
import { useAppSelector } from "@/store/hooks";
import styles from "./DashboardHero.module.css";
// import AnimatedGlowOrb from "../ui/AnimatedGlowOrb/AnimatedGlowOrb";

export default function DashboardHero() {
  const user = useAppSelector((s) => s.auth.user);
  const firstName =
    user?.given_name ||
    user?.name?.split(" ")[0] ||
    user?.email?.split("@")[0] ||
    "User";

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return "Good Morning";
    if (hour < 18) return "Good Afternoon";
    return "Good Evening";
  };

  const greeting = getGreeting();

  return (
    <Container
      size="lg"
      h="100%"
      display="flex"
      className={styles.heroContainer}
    >
      <Box className={styles.heroContent}>
        <Box mb="2rem" mt="1rem">
          <Box className={styles.imageContainer}>
            {/* Rotating 50/50 Green/Blue Aura */}
            <Box className={styles.auraEffect} />

            {/* Orb Image */}
            <img
              src="/images/glowOrb.png"
              alt="Logo"
              className={styles.heroImage}
            />
            {/* <AnimatedGlowOrb size={200} /> */}
          </Box>
        </Box>

        <Stack gap="xs" align="center" mb="3rem">
          <Title
            order={1}
            size={34}
            fw={700}
            c="var(--app-text-primary)"
            ta="center"
          >
            {greeting}, {firstName}
          </Title>
          <Title
            order={2}
            size={34}
            fw={700}
            c="var(--app-text-primary)"
            ta="center"
          >
            What's on{" "}
            <Text span className={styles.highlightText} inherit>
              your mind?
            </Text>
          </Title>
          <Text c="dimmed" size="md" maw={500} ta="center" mt="sm">
            I'm Uniserv - your AI-powered Utility Copilot. Find answers to your questions quickly or choose a category below to refine results
          </Text>
        </Stack>
      </Box>
    </Container>
  );
}