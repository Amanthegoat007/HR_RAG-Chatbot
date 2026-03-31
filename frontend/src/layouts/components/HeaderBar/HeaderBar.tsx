import {
  Group,
  Burger,
  Box,
  Image,
  Avatar,
  Tooltip,
} from "@mantine/core";
import { useLayout } from "@/layouts/LayoutContext";
import { useAppSelector } from "@/store/hooks";
import { buildIdentityPresentation } from "@/utils/identityPresentation";

export default function HeaderBar() {
  const { mobileOpened, toggleMobile, hasSidebar } = useLayout();

  const user = useAppSelector((state) => state.auth.user);
  const identity = buildIdentityPresentation(user);

  return (
    <Group
      h="100%"
      justify="space-between"
      align="center"
      style={{ width: "100%" }}
    >
      <Group gap="sm">
        {hasSidebar && (
          <Burger
            opened={mobileOpened}
            onClick={toggleMobile}
            hiddenFrom="sm"
            size="sm"
            color="var(--app-text-primary)"
          />
        )}
        <Box>
          <Image src="/images/logo-esyasoft.png" w={100} />
        </Box>
      </Group>

      <Tooltip label={identity.displayName}>
        <Avatar radius="xl" src={null} alt="User profile" color="green">
          {identity.initials}
        </Avatar>
      </Tooltip>
    </Group>
  );
}
