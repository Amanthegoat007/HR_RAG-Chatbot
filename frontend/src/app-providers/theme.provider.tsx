import { MantineProvider } from "@mantine/core";
import { theme } from "@/theme";

interface ThemeProviderProps {
  children: React.ReactNode;
}

export function ThemeProviderComponent({ children }: ThemeProviderProps) {
  // Get initial color scheme from localStorage or default to 'light'
  const defaultColorScheme =
    (localStorage.getItem("mantine-color-scheme") as
      | "light"
      | "dark"
      | "auto") || "light";

  return (
    <MantineProvider theme={theme} defaultColorScheme={defaultColorScheme}>
      {children}
    </MantineProvider>
  );
}
