import { configureStore } from "@reduxjs/toolkit";
import authReducer from "./slices/authSlice";
import chatReducer from "./slices/chatSlice";
import settingsReducer from "./slices/settingsSlice";
import type { AuthState } from "@/types/auth.types";
import type { ChatState } from "@/types/chat.types";
import type { SettingsState } from "@/types/settings.types";

import type { RootState } from "./store.types";

export const store = configureStore({
  reducer: {
    auth: authReducer,
    chat: chatReducer,
    settings: settingsReducer,
  },
});

export type AppDispatch = typeof store.dispatch;
export type { RootState } from "./store.types";
