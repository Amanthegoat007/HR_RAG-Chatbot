import { Box, SimpleGrid, Text } from "@mantine/core";
import {
  TbAlertTriangle,
  TbActivity,
  TbUsers,
  TbHeartbeat,
} from "react-icons/tb";
import { IconType } from "react-icons";
import { QuickActionCard } from "@/components/ui";
import {
  useAccessControl,
  type AccessControlConfig,
} from "@/hooks/useAccessControl";

import { useNavigate } from "react-router-dom";

export default function QuickAccessCategories() {
  const navigate = useNavigate();
  const { hasAccess } = useAccessControl();

  // Define the configuration for quick actions inside to use navigate
  const QUICK_ACTIONS: (AccessControlConfig & {
    title: string;
    description: string;
    icon: IconType;
    onClick: () => void;
  })[] = [
    {
      title: "Theft Detection",
      description: "View Real Time data and detect anomalies",
      icon: TbAlertTriangle,
      onClick: () => {
        navigate("/theft-detection");
      },
      allowedRoles: ["ROLE_ADMINISTRATOR", "ROLE_FIELD_OFFICER"],
      // allowedGroups: ['/zones/ZONE_SOUTH'],
      requireAll: true,
    },
    {
      title: "Load Forecasting",
      description: "View Real Time data and detect patterns",
      icon: TbActivity,
      onClick: () => {
        navigate("/load-forecasting");
      },
      allowedRoles: ["ROLE_ADMINISTRATOR"],
      // allowedGroups: ['/zones/ZONE_SOUTH'],
      requireAll: true,
    },
    {
      title: "Defaulter Analysis",
      description: "Predictive analysis for payments",
      icon: TbUsers,
      onClick: () => {
        navigate("/defaulter-analysis");
      },
      allowedRoles: ["ROLE_ADMINISTRATOR", "ROLE_FIELD_OFFICER"],
      // allowedGroups: ['/zones/ZONE_SOUTH'],
      requireAll: true,
    },
    {
      title: "Asset Health",
      description: "Monitor health and aging of assets",
      icon: TbHeartbeat,
      onClick: () => {
        navigate("/asset-health");
      },
      allowedRoles: ["ROLE_ADMINISTRATOR", "ROLE_FIELD_OFFICER"],
      // allowedGroups: ['/zones/ZONE_SOUTH'],
      requireAll: true,
    },
    {
      title: "Consumer Indexation",
      description: "Monitor health and aging of assets",
      icon: TbHeartbeat,
      onClick: () => {
        navigate("/consumer-indexation");
      },
      allowedRoles: ["ROLE_ADMINISTRATOR", "ROLE_FIELD_OFFICER"],
      // allowedGroups: ['/zones/ZONE_SOUTH'],
      requireAll: true,
    },
  ];

  // Filter actions based on roles and groups
  const visibleActions = QUICK_ACTIONS.filter((action) => {
    return hasAccess({
      allowedRoles: action.allowedRoles,
      allowedGroups: action.allowedGroups,
      requireAll: action.requireAll,
    });
  });

  if (visibleActions.length === 0) return null;

  return (
    <Box w="100%" maw={900} mb="xl">
      <Text fw={600} size="lg" mb="md" c="var(--app-text-primary)">
        Quick Access Categories
      </Text>
      <SimpleGrid cols={{ base: 1, xs: 2, sm: 2, md: 4 }} spacing="md">
        {visibleActions.map((action) => (
          <QuickActionCard
            key={action.title}
            title={action.title}
            description={action.description}
            icon={action.icon}
            onClick={action.onClick}
          />
        ))}
      </SimpleGrid>
    </Box>
  );
}
