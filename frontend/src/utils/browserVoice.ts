export type VoiceCapabilityStatus =
  | "ready"
  | "unsupported"
  | "permission-denied"
  | "errored";

export interface VoiceCapability {
  status: VoiceCapabilityStatus;
  supported: boolean;
  message: string;
}

export function getSpeechRecognitionConstructor(): any {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

export function getBrowserVoiceCapability(): VoiceCapability {
  const Recognition = getSpeechRecognitionConstructor();
  if (!Recognition) {
    return {
      status: "unsupported",
      supported: false,
      message: "Voice input is available in Chromium-based browsers that support speech recognition.",
    };
  }

  return {
    status: "ready",
    supported: true,
    message: "Voice input is ready in this browser.",
  };
}
