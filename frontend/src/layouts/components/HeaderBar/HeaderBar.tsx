import {
  Group,
  Title,
  Burger,
  Box,
  Image,
  Avatar,
} from "@mantine/core";
import { useLayout } from "@/layouts/LayoutContext";
import { useAppSelector } from "@/store/hooks";

export default function HeaderBar() {
  const { mobileOpened, toggleMobile, hasSidebar } = useLayout();

  const user = useAppSelector((state) => state.auth.user);

  const getInitials = (u: any) => {
    if (u?.given_name && u?.family_name) {
      return `${u.given_name[0]}${u.family_name[0]}`.toUpperCase();
    }
    if (u?.name) {
      return u.name.substring(0, 2).toUpperCase();
    }
    if (u?.email) {
      return u.email.substring(0, 2).toUpperCase();
    }
    return "U";
  };

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
            color="#000000"
          />
        )}
        <Title
          order={4}
          style={{
            color: "#000000",
            display: "flex",
            alignItems: "center",
            gap: "4px",
          }}
        >
          <Box>
            <Image src="/images/logo-esyasoft.png" w={100} />
          </Box>
        </Title>
      </Group>

      <Avatar
        radius="xl"
        src={null}
        alt="User profile"
        color="green"
      >
        {getInitials(user)}
      </Avatar>
    </Group>
  );
}
