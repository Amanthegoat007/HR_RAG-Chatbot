import { Box, LoadingOverlay } from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LoginForm, LoginFeaturesPanel } from "./components";

import { useAppSelector } from "@/store/hooks";

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
          height: "100vh",
          width: "100vw",
          overflow: "hidden",
        }}
      >
        <LoadingOverlay
          visible={loading || (isInitialLoading && !isInitialized)}
          zIndex={1000}
          overlayProps={{ blur: 2 }}
        />

        {/* Left Panel - Features */}
        <LoginFeaturesPanel />

        {/* Right Panel - Login Form */}
        <LoginForm setLoading={setLoading} />
      </Box>
  );
}
