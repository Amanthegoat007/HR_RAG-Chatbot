import { Box, Container, Stack, Text, Title } from "@mantine/core";
import { useAppSelector } from "@/store/hooks";
import { useGreetingClock } from "@/hooks/useGreetingClock";
import { buildGreetingCopy } from "@/utils/greetingPhraseEngine";
import { buildIdentityPresentation } from "@/utils/identityPresentation";
import styles from "./DashboardHero.module.css";

export interface DashboardHeroProps {
  variant?: "default" | "landing";
}

export default function DashboardHero({
  variant = "default",
}: DashboardHeroProps) {
  const isLanding = variant === "landing";
  const user = useAppSelector((s) => s.auth.user);
  const now = useGreetingClock();
  const identity = buildIdentityPresentation(user);
  const greetingCopy = buildGreetingCopy(identity, now);

  if (isLanding) {
    return (
      <Container size="md" className={styles.heroContainer}>
        <Box className={styles.landingIntro}>
          <Box className={styles.landingBadge}>
            <img
              src="/images/glowOrb.png"
              alt=""
              aria-hidden="true"
              className={styles.landingBadgeImage}
            />
            <Text className={styles.landingBadgeLabel}>{greetingCopy.eyebrow}</Text>
          </Box>

          <Stack gap={8} align="center" className={styles.landingCopyStack}>
            <Title order={1} className={styles.landingHeading}>
              {greetingCopy.headline}
            </Title>
            <Text className={styles.promptLine} ta="center">
              {greetingCopy.prompt}
            </Text>
            <Text c="dimmed" className={styles.landingSubtitle} ta="center">
              {greetingCopy.subtitle}
            </Text>
          </Stack>
        </Box>
      </Container>
    );
  }

  return (
    <Container size="lg" className={styles.heroContainer}>
      <Box className={`${styles.heroContent} ${styles.heroDefault}`}>
        <Box className={styles.heroGlow} />
        <Box className={styles.heroGlowSecondary} />

        <Box mb="lg" mt="xs" className={styles.visualCluster}>
          <Box className={styles.imageContainer}>
            <Box className={styles.auraEffect} />
            <img
              src="/images/glowOrb.png"
              alt="Logo"
              className={styles.heroImage}
            />
          </Box>
        </Box>

        <Stack gap="xs" align="center" className={styles.copyStack}>
          <Title order={1} className={styles.heroTitle}>
            {greetingCopy.headline}
          </Title>
          <Title order={2} className={`${styles.heroTitle} ${styles.heroTitleAccent}`}>
            {greetingCopy.prompt}
          </Title>
          <Text
            c="dimmed"
            size="md"
            className={styles.supportingCopy}
            ta="center"
          >
            {greetingCopy.subtitle}
          </Text>
        </Stack>
      </Box>
    </Container>
  );
}
