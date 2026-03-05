import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import { axiosClient } from "@/services/axiosClient";
import { AxiosError } from "axios";
import type { User, LoginCredentials } from "@/types/auth.types";

export interface AuthState {
  user: User | null;
  roles: string[];
  groups: string[];
  isAuthenticated: boolean;
  error: string | null;
  isInitialLoading: boolean;
  isInitialized: boolean;
}

export const loginWithCredentials = createAsyncThunk(
  "auth/login",
  async (payload: LoginCredentials, thunkAPI) => {
    try {
      const res = await axiosClient.post("/api/auth/login", {
        username: payload.username,
        password: payload.password,
      });

      // Fetch user profile immediately after login
      const meRes = await axiosClient.get("/api/auth/me");

      return {
        user: meRes.data,
      };
    } catch (err) {
      console.error("Login error:", err);
      if (err instanceof AxiosError) {
        const msg =
          err.response?.data?.error_description ||
          err.response?.data?.error ||
          err.message ||
          "Login failed";
        return thunkAPI.rejectWithValue(msg);
      }
      return thunkAPI.rejectWithValue("An unexpected error occurred");
    }
  },
);

export const checkAuthStatus = createAsyncThunk(
  "auth/checkStatus",
  async (_, thunkAPI) => {
    try {
      const res = await axiosClient.get("/api/auth/me");
      return { user: res.data }; // Expected { user: { ... } }
    } catch (err) {
      return thunkAPI.rejectWithValue("Not authenticated");
    }
  },
);

export const refreshAccessToken = createAsyncThunk(
  "auth/refresh",
  async (_, thunkAPI) => {
    try {
      const res = await axiosClient.post("/api/auth/refresh");
      return res.data;
    } catch (err) {
      return thunkAPI.rejectWithValue("Token refresh failed");
    }
  },
);

const authSlice = createSlice({
  name: "auth",
  initialState: {
    user: null,
    roles: [],
    groups: [],
    isAuthenticated: false,
    error: null,
    isInitialLoading: false,
    isInitialized: false,
  } as AuthState,
  reducers: {
    logout(state) {
      state.user = null;
      state.roles = [];
      state.groups = [];
      state.isAuthenticated = false;
      state.error = null;

      axiosClient.post("/api/auth/logout").catch(console.error);
    },
  },
  extraReducers: (builder) => {
    builder.addCase(loginWithCredentials.fulfilled, (state, action) => {
      state.user = action.payload?.user || null;
      state.roles = action.payload?.user?.roles || [];
      state.groups = action.payload?.user?.groups || [];
      state.isAuthenticated = true;
      state.error = null;
    });

    builder.addCase(loginWithCredentials.rejected, (state, action) => {
      state.error = action.payload as string;
      state.isAuthenticated = false;
    });

    builder.addCase(loginWithCredentials.pending, (state) => {
      state.error = null;
    });

    builder.addCase(refreshAccessToken.fulfilled, (state) => {
      // Nothing to update in state, tokens are in cookies
      state.isAuthenticated = true;
    });

    builder.addCase(checkAuthStatus.pending, (state) => {
      state.isInitialLoading = true;
    });

    builder.addCase(checkAuthStatus.fulfilled, (state, action) => {
      state.user = action.payload?.user || null;
      state.roles = action.payload?.user?.roles || [];
      state.groups = action.payload?.user?.groups || [];
      state.isAuthenticated = true;
      state.isInitialLoading = false;
      state.isInitialized = true;
    });

    builder.addCase(checkAuthStatus.rejected, (state) => {
      state.isAuthenticated = false;
      state.isInitialLoading = false;
      state.isInitialized = true;
    });
  },
});

export const { logout } = authSlice.actions;
export default authSlice.reducer;
