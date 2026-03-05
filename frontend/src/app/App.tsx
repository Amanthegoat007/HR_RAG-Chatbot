import { useEffect } from "react";
import AppRoutes from "@/routes/AppRoutes";
import { useAppDispatch } from "@/store/hooks";
import { checkAuthStatus } from "@/store/slices/authSlice";

export default function App() {
  const dispatch = useAppDispatch();

  useEffect(() => {
    dispatch(checkAuthStatus());
  }, [dispatch]);

  return <AppRoutes />;
}
