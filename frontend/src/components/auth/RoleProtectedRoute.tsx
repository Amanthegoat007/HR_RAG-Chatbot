import { Navigate, Outlet } from "react-router-dom";
import { useEffect } from "react";
import { checkAuthStatus } from "@/store/slices/authSlice";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { Box, Title, Button, Stack, LoadingOverlay } from "@mantine/core";
import { Link } from "react-router-dom";

interface RoleProtectedRouteProps {
  roles: string[];
  children: React.ReactNode;
}

export default function RoleProtectedRoute({
  roles,
  children,
}: RoleProtectedRouteProps) {
  const {
    isAuthenticated,
    roles: userRoles,
    isInitialized,
    isInitialLoading,
  } = useAppSelector((s) => s.auth);
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (!isInitialized && !isInitialLoading) {
      dispatch(checkAuthStatus());
    }
  }, [isInitialized, isInitialLoading, dispatch]);

  if (!isInitialized || (isInitialLoading && !isAuthenticated)) {
    return (
      <Box h="100vh" pos="relative">
        <LoadingOverlay visible={true} />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const hasAccess = roles.some((r) => userRoles.includes(r));

  if (!hasAccess) {
    return (
      <Box
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Stack align="center">
          <Title order={2}>403 - Forbidden</Title>
          <p>You do not have permission to access this page.</p>
          <Button component={Link} to="/copilot">
            Back to Dashboard
          </Button>
        </Stack>
      </Box>
    );
  }

  return <>{children}</>;
}
