import {
  Stack,
  Text,
  Box,
  Title,
  Image,
  ThemeIcon,
  SimpleGrid,
  Group,
  Paper,
} from "@mantine/core";
import {
  TbBook2,
  TbPaperclip,
  TbQuote,
  TbDatabase,
} from "react-icons/tb";
import { designTokens } from "@/theme/designTokens";

export default function LoginFeaturesPanel() {
  return (
    <Box
      style={{
        flex: 1,
        background:
          "radial-gradient(circle at 10% 0%, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0) 18%), linear-gradient(165deg, #15251a 0%, #1d4025 48%, #2f9c42 100%)",
        color: "var(--mantine-color-white)",
        padding: designTokens.spacing.vh(4),
        margin: designTokens.spacing.vh(2),
        borderRadius: designTokens.radius.md,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        position: "relative",
        overflow: "hidden",
        boxShadow: "0 28px 48px rgba(0, 0, 0, 0.28)",
      }}
      visibleFrom="md"
    >
      {/* Decorative Circle Pattern */}
      <Box
        style={{
          position: "absolute",
          top: "10%",
          right: "-5%",
          width: "50%",
          height: "50%",
          opacity: 0.28,
          backgroundImage: 'url("/images/login_pattern.png")',
          backgroundSize: "contain",
          backgroundRepeat: "no-repeat",
          pointerEvents: "none",
        }}
      />
      <Box>
        <Image src="/images/logo-esyasoft.png" w={180} />
      </Box>

      <Stack gap="xl">
        <Box p="xl">
          <Title
            order={1}
            size={48}
            fw={700}
            c="#eaf3df"
            opacity={0.96}
            style={{ lineHeight: 1.08, marginBottom: 12, letterSpacing: "-0.03em" }}
          >
            Esyasoft HR Copilot
          </Title>
          <Text size="lg" c="rgba(236, 245, 229, 0.88)" fw={500}>
            One workspace for every HR answer
          </Text>
          <Box
            w={72}
            h={4}
            bg="rgba(0, 224, 140, 0.85)"
            mt="lg"
            style={{ borderRadius: 999 }}
          />
        </Box>

        <Paper
          p="xl"
          style={{
            backgroundColor: "rgba(31, 83, 37, 0.34)",
            backdropFilter: "blur(16px)",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 28,
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05)",
          }}
        >
          <SimpleGrid cols={2} spacing="xl" verticalSpacing="xl">
            <FeatureItem
              icon={TbBook2}
              label="Policies, leave, and benefits guidance"
            />
            <FeatureItem
              icon={TbPaperclip}
              label="Session uploads for case-specific questions"
            />
            <FeatureItem
              icon={TbQuote}
              label="Grounded answers with cited sources"
            />
            <FeatureItem icon={TbDatabase} label="Shared HR knowledge library" />
          </SimpleGrid>
        </Paper>
      </Stack>
    </Box>
  );
}

function FeatureItem({
  icon: Icon,
  label,
}: {
  icon: React.ElementType;
  label: string;
}) {
  return (
    <Group gap="sm" align="center" wrap="nowrap">
      <ThemeIcon
        size="lg"
        radius="md"
        style={{
          background:
            "linear-gradient(180deg, rgba(0, 212, 131, 0.95) 0%, rgba(0, 176, 109, 0.95) 100%)",
          color: "#f4fffa",
          boxShadow: "0 10px 20px rgba(0, 0, 0, 0.16)",
        }}
      >
        <Icon size={20} />
      </ThemeIcon>
      <Text
        size="sm"
        c="rgba(234, 243, 228, 0.9)"
        fw={600}
        style={{ lineHeight: 1.3, fontSize: "1.02rem" }}
      >
        {label}
      </Text>
    </Group>
  );
}
