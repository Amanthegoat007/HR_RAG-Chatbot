import { AppShell } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./components/Sidebar/Sidebar";
import { LayoutContext } from "./LayoutContext";

export default function CopilotLayout() {
  const [opened, { toggle }] = useDisclosure();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <LayoutContext.Provider
      value={{ mobileOpened: opened, toggleMobile: toggle, hasSidebar: true }}
    >
      <AppShell
        navbar={{
          width: collapsed ? 60 : 260,
          breakpoint: "sm",
          collapsed: { mobile: !opened },
        }}
        padding={0}
      >
        <AppShell.Navbar>
          <Sidebar collapsed={collapsed} onToggle={setCollapsed} />
        </AppShell.Navbar>

        <AppShell.Main
          style={{ height: "100dvh", display: "flex", flexDirection: "column" }}
        >
          <Outlet />
        </AppShell.Main>
      </AppShell>
    </LayoutContext.Provider>
  );
}
