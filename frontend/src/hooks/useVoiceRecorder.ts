import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getBrowserVoiceCapability,
  getSpeechRecognitionConstructor,
  type VoiceCapability,
} from "@/utils/browserVoice";
import {
  SpeechRecognition,
  SpeechRecognitionErrorEvent,
  SpeechRecognitionEvent,
} from "@/types/speech.types";

const LANGUAGE_MAP: Record<string, string> = {
  en: "en-US",
  hi: "hi-IN",
  kn: "kn-IN",
  bn: "bn-IN",
  mr: "mr-IN",
  ta: "ta-IN",
  te: "te-IN",
  gu: "gu-IN",
  ml: "ml-IN",
};

export const useVoiceRecorder = (
  onTranscriptionComplete: (result: {
    text: string;
    language?: string;
  }) => void,
  onInterimTranscription?: (text: string) => void,
  language: string = "en",
) => {
  const [isRecording, setIsRecording] = useState(false);
  const [capability, setCapability] = useState<VoiceCapability>(
    getBrowserVoiceCapability(),
  );
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const finalTranscriptRef = useRef("");
  const interimTranscriptRef = useRef("");
  const cancelledRef = useRef(false);

  useEffect(() => {
    setCapability(getBrowserVoiceCapability());
  }, []);

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  const commitTranscript = useCallback(() => {
    const finalText = finalTranscriptRef.current.trim();
    if (!finalText) return;
    onTranscriptionComplete({
      text: finalText,
      language,
    });
    finalTranscriptRef.current = "";
    interimTranscriptRef.current = "";
  }, [language, onTranscriptionComplete]);

  const startRecording = useCallback(() => {
    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      setCapability({
        status: "unsupported",
        supported: false,
        message:
          "Voice input is available in Chromium-based browsers that support speech recognition.",
      });
      return;
    }

    try {
      const recognition = new Recognition() as SpeechRecognition;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = LANGUAGE_MAP[language] || "en-US";

      cancelledRef.current = false;
      finalTranscriptRef.current = "";
      interimTranscriptRef.current = "";

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        let interimText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const transcript = event.results[index][0]?.transcript || "";
          if (event.results[index].isFinal) {
            finalTranscriptRef.current = `${finalTranscriptRef.current} ${transcript}`.trim();
          } else {
            interimText += transcript;
          }
        }
        interimTranscriptRef.current = interimText.trim();
        onInterimTranscription?.(
          `${finalTranscriptRef.current} ${interimTranscriptRef.current}`.trim(),
        );
      };

      recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
        const status =
          event.error === "not-allowed" || event.error === "service-not-allowed"
            ? "permission-denied"
            : "errored";
        setCapability({
          status,
          supported: false,
          message:
            status === "permission-denied"
              ? "Microphone permission was denied. Allow microphone access to use voice input."
              : "Voice input could not start in this browser session.",
        });
        setIsRecording(false);
      };

      recognition.onend = () => {
        const shouldCommit = !cancelledRef.current;
        setIsRecording(false);
        recognitionRef.current = null;
        if (shouldCommit) {
          commitTranscript();
        } else {
          finalTranscriptRef.current = "";
          interimTranscriptRef.current = "";
        }
      };

      recognition.start();
      recognitionRef.current = recognition;
      setCapability(getBrowserVoiceCapability());
      setIsRecording(true);
    } catch (error) {
      setCapability({
        status: "errored",
        supported: false,
        message: "Voice input could not start in this browser session.",
      });
      setIsRecording(false);
    }
  }, [commitTranscript, language, onInterimTranscription]);

  const stopRecording = useCallback(() => {
    cancelledRef.current = false;
    recognitionRef.current?.stop();
  }, []);

  const cancelRecording = useCallback(() => {
    cancelledRef.current = true;
    recognitionRef.current?.abort();
    recognitionRef.current = null;
    finalTranscriptRef.current = "";
    interimTranscriptRef.current = "";
    setIsRecording(false);
  }, []);

  return useMemo(
    () => ({
      isRecording,
      isLoading: false,
      capability,
      startRecording,
      stopRecording,
      cancelRecording,
    }),
    [capability, cancelRecording, isRecording, startRecording, stopRecording],
  );
};
