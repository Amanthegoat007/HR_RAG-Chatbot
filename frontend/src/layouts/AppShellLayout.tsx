import { AppShell } from '@mantine/core';
import { Outlet } from 'react-router-dom';
import { LayoutContext } from './LayoutContext';

export default function AppShellLayout() {
  return (
    <LayoutContext.Provider value={{ mobileOpened: false, toggleMobile: () => { }, hasSidebar: false }}>
      <AppShell padding={0}>
        <AppShell.Main
          style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }} >
          <Outlet />
        </AppShell.Main>
      </AppShell>
    </LayoutContext.Provider>
  );
}
