import { createContext, useContext } from "react";

import type { LayoutContextType } from "./LayoutContext.types";

export type { LayoutContextType };

export const LayoutContext = createContext<LayoutContextType | null>(null);

export const useLayout = () => {
  const context = useContext(LayoutContext);
  if (!context) {
    return {
      mobileOpened: false,
      toggleMobile: () => {},
      hasSidebar: false,
    };
  }
  return context;
};
