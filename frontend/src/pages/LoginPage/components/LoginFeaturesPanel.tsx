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
  TbChartPie,
  TbAlertTriangle,
  TbUsers,
  TbActivity,
} from "react-icons/tb";
import { designTokens } from "@/theme/designTokens";

export default function LoginFeaturesPanel() {
  return (
    <Box
      style={{
        flex: 1,
        background: designTokens.gradients.loginPanel,
        backgroundSize: "100% 100%",
        color: "var(--mantine-color-white)",
        padding: designTokens.spacing.vh(4),
        margin: designTokens.spacing.vh(2),
        borderRadius: designTokens.radius.md,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        position: "relative",
        overflow: "hidden",
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
          opacity: 0.2,
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
            size={36}
            fw={700}
            c="dark.8"
            opacity={0.9}
            style={{ lineHeight: 1.2, marginBottom: 8 }}
          >
            See the Network Thinking
          </Title>
          <Text size="md" c="dark.7" fw={500}>
            Utility Analytics Platform
          </Text>
          <Box w={60} h={4} bg="brand.5" mt="xs" style={{ borderRadius: 2 }} />
        </Box>

        <Paper
          p="xl"
          style={{
            backgroundColor: "rgba(255,255,255,0.1)",
            backdropFilter: "blur(10px)",
          }}
        >
          <SimpleGrid cols={2} spacing="xl" verticalSpacing="xl">
            <FeatureItem
              icon={TbChartPie}
              label="AI-Powered Analytics & Insights"
            />
            <FeatureItem icon={TbActivity} label="Real-time Load Forecasting" />
            <FeatureItem
              icon={TbAlertTriangle}
              label="Theft & Anomaly Detection"
            />
            <FeatureItem icon={TbUsers} label="Predictive Defaulter Analysis" />
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
      <ThemeIcon color="green" variant="dark" size="lg" radius="md">
        <Icon size={20} />
      </ThemeIcon>
      <Text size="sm" c="dark.6" fw={600} style={{ lineHeight: 1.3 }}>
        {label}
      </Text>
    </Group>
  );
}
