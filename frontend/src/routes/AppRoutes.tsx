import { Routes, Route, Navigate } from "react-router-dom";
import { LoadingOverlay, Box } from "@mantine/core";
import CopilotLayout from "@/layouts/CopilotLayout";
import AppShellLayout from "@/layouts/AppShellLayout";
import LoginPage from "@/pages/LoginPage";
import CoPilotPage from "@/pages/CoPilotPage";
import { DocumentManagementPage } from "@/pages";
import { ProtectedRoute, RoleProtectedRoute } from "@/components/auth";
import { useAppSelector } from "@/store/hooks";

// We will add DocumentManagementPage here later in Phase 6

export default function AppRoutes() {
  const { user, isInitialLoading } = useAppSelector((s) => s.auth);

  if (isInitialLoading) {
    return (
      <Box h="100vh" pos="relative">
        <LoadingOverlay visible={true} />
      </Box>
    );
  }

  return (
    <Routes>
      {/* ROOT DECISION */}
      <Route
        path="/"
        element={<Navigate to={user ? "/copilot" : "/login"} replace />}
      />

      {/* PUBLIC */}
      <Route path="/login" element={<LoginPage />} />

      {/* CO-PILOT LAYOUT ROUTES (Sidebar + Header typically) */}
      <Route element={<CopilotLayout />}>
        <Route
          path="/copilot"
          element={
            <ProtectedRoute>
              <CoPilotPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/copilot/c/:conversationId"
          element={
            <ProtectedRoute>
              <CoPilotPage />
            </ProtectedRoute>
          }
        />

        {/* Admin Document Management */}
        <Route
          path="/documents"
          element={
            <RoleProtectedRoute roles={["ROLE_ADMIN", "ROLE_ADMINISTRATOR"]}>
              <DocumentManagementPage />
            </RoleProtectedRoute>
          }
        />
      </Route>

      {/* FALLBACK */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
