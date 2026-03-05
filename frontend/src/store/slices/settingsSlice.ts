import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { SettingsState } from "@/types/settings.types";

const getInitialState = (): SettingsState => {
  try {
    const savedLang = localStorage.getItem("primaryLanguage");
    const savedMethod = localStorage.getItem("speechRecognitionMethod");
    return {
      primaryLanguage: savedLang || "en",
      speechRecognitionMethod: savedMethod || "review",
    };
  } catch (error) {
    console.error("Failed to load settings from localStorage:", error);
    return {
      primaryLanguage: "en",
      speechRecognitionMethod: "review",
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
    setSpeechRecognitionMethod(state, action: PayloadAction<string>) {
      state.speechRecognitionMethod = action.payload;
      try {
        localStorage.setItem("speechRecognitionMethod", action.payload);
      } catch (error) {
        console.error(
          "Failed to save speechRecognitionMethod to localStorage:",
          error,
        );
      }
    },
  },
});

export const { setPrimaryLanguage, setSpeechRecognitionMethod } =
  settingsSlice.actions;
export default settingsSlice.reducer;
