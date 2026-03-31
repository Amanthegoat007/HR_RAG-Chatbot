import { Drawer } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { motionTokens } from "@/theme/motion";
import Sidebar from "./components/Sidebar/Sidebar";
import { LayoutContext } from "./LayoutContext";
import classes from "./CopilotLayout.module.css";

const DESKTOP_SIDEBAR_EXPANDED = 280;
const DESKTOP_SIDEBAR_COLLAPSED = 76;

export default function CopilotLayout() {
  const [opened, { toggle, close }] = useDisclosure(false);
  const [collapsed, setCollapsed] = useState(false);
  const isMobile = useMediaQuery("(max-width: 48em)");

  useEffect(() => {
    if (!isMobile) {
      close();
    }
  }, [close, isMobile]);

  return (
    <LayoutContext.Provider
      value={{ mobileOpened: opened, toggleMobile: toggle, hasSidebar: true }}
    >
      <div className={classes.shell}>
        {!isMobile && (
          <motion.aside
            className={classes.desktopSidebar}
            initial={false}
            animate={{
              width: collapsed
                ? DESKTOP_SIDEBAR_COLLAPSED
                : DESKTOP_SIDEBAR_EXPANDED,
            }}
            transition={{
              duration: motionTokens.duration.base,
              ease: motionTokens.ease.standard,
            }}
          >
            <Sidebar collapsed={collapsed} onToggle={setCollapsed} />
          </motion.aside>
        )}

        <motion.main layout className={classes.main}>
          <Outlet />
        </motion.main>

        <Drawer
          opened={opened && !!isMobile}
          onClose={close}
          withCloseButton={false}
          padding={0}
          size={286}
          classNames={{
            content: classes.mobileDrawerContent,
            body: classes.mobileDrawerBody,
          }}
          overlayProps={{ backgroundOpacity: 0.42, blur: 5 }}
        >
          <Sidebar collapsed={false} onToggle={() => undefined} />
        </Drawer>
      </div>
    </LayoutContext.Provider>
  );
}
