import type { AuthState } from "@/types/auth.types";
import type { ChatState } from "@/types/chat.types";
import type { SettingsState } from "@/types/settings.types";

export interface RootState {
  auth: AuthState;
  chat: ChatState;
  settings: SettingsState;
}
