import { Navigate, Outlet } from "react-router-dom";
import { useEffect } from "react";
import { useAppSelector, useAppDispatch } from "@/store/hooks";
import { checkAuthStatus } from "@/store/slices/authSlice";
import { Box, LoadingOverlay } from "@mantine/core";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isInitialized, isInitialLoading } = useAppSelector(
    (s) => s.auth,
  );
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

  return <>{children}</>;
}
