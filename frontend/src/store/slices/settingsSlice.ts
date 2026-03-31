import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { SettingsState } from "@/types/settings.types";

const getInitialState = (): SettingsState => {
  try {
    const savedLang = localStorage.getItem("primaryLanguage");
    return {
      primaryLanguage: savedLang || "en",
    };
  } catch (error) {
    console.error("Failed to load settings from localStorage:", error);
    return {
      primaryLanguage: "en",
    };
  }
};

const initialState: SettingsState = getInitialState();

const settingsSlice = createSlice({
  name: "settings",
  initialState,
  reducers: {
    setPrimaryLanguage(state, action: PayloadAction<string>) {
      state.primaryLanguage = action.payload;
      try {
        localStorage.setItem("primaryLanguage", action.payload);
      } catch (error) {
        console.error("Failed to save primaryLanguage to localStorage:", error);
      }
    },
  },
});

export const { setPrimaryLanguage } = settingsSlice.actions;
export default settingsSlice.reducer;
