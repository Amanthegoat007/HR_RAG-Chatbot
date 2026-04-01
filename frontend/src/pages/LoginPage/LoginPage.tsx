import { Box, LoadingOverlay } from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LoginForm, LoginFeaturesPanel } from "./components";

import { useAppSelector } from "@/store/hooks";
import { designTokens } from "@/theme/designTokens";

export default function LoginPage() {
  const navigate = useNavigate();
  const { user, isAuthenticated, isInitialLoading, isInitialized } =
    useAppSelector((s) => s.auth);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isInitialized && (isAuthenticated || user)) {
      navigate("/copilot", { replace: true });
    }
  }, [isAuthenticated, user, navigate, isInitialized]);

  return (
    <Box
      style={{
        display: "flex",
        minHeight: "100vh",
        width: "100vw",
        overflow: "hidden",
        background:
          "radial-gradient(circle at 70% 12%, rgba(91, 117, 181, 0.18) 0%, rgba(91, 117, 181, 0) 30%), #171a1f",
      }}
    >
      <LoadingOverlay
        visible={loading || (isInitialLoading && !isInitialized)}
        zIndex={1000}
        overlayProps={{ blur: 2, backgroundOpacity: 0.2 }}
        loaderProps={{ color: designTokens.colors.brand[5] }}
      />

      {/* Left Panel - Features */}
      <LoginFeaturesPanel />

      {/* Right Panel - Login Form */}
      <LoginForm setLoading={setLoading} />
    </Box>
  );
}
