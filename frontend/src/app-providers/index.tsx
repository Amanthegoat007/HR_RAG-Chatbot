import { BrowserRouter } from "react-router-dom";
import { ReduxProvider } from "./redux.provider";
import { ThemeProviderComponent } from "./theme.provider";

interface AppProvidersProps {
  children: React.ReactNode;
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <ReduxProvider>
      <BrowserRouter>
        <ThemeProviderComponent>{children}</ThemeProviderComponent>
      </BrowserRouter>
    </ReduxProvider>
  );
}

// Export individual providers for flexibility
export { ReduxProvider } from "./redux.provider";
export { ThemeProviderComponent as ThemeProvider } from "./theme.provider";
