import { useState, useRef, useCallback, useEffect } from "react";
import { transcribeApi } from "@/services/api";

import {
  SpeechRecognitionEvent,
  SpeechRecognitionErrorEvent,
  SpeechRecognition,
} from "@/types/speech.types";

export const useVoiceRecorder = (
  onTranscriptionComplete: (result: {
    text: string;
    language?: string;
  }) => void,
  onInterimTranscription?: (text: string) => void,
  method: string = "review",
  language: string = "en",
) => {
  console.log(
    `[VoiceRecorder] 🎤 Initialized with method: ${method} (Lang: ${language})`,
  );
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const finalTranscriptRef = useRef("");
  const isCancelledRef = useRef(false);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
    };
  }, []);

  const startRecording = useCallback(async () => {
    console.log(`[VoiceRecorder] 🎙️ Starting recording with method: ${method}`);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      console.log(`[VoiceRecorder] ✅ Microphone access granted`);

      if (method === "google-webkit") {
        console.log(`[VoiceRecorder] 🌐 Using Google Webkit (browser API)`);
        // 1. Setup Web Speech API for real-time results
        const SpeechRecognition =
          window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
          const recognition = new SpeechRecognition();
          recognition.continuous = true;
          recognition.interimResults = true;

          // Map short codes to BCP 47 codes for browser
          const langMap: Record<string, string> = {
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
          recognition.lang = langMap[language] || "en-US";

          finalTranscriptRef.current = "";

          recognition.onresult = (event: SpeechRecognitionEvent) => {
            let interimTranscript = "";
            for (let i = event.resultIndex; i < event.results.length; ++i) {
              if (event.results[i].isFinal) {
                finalTranscriptRef.current += event.results[i][0].transcript;
              } else {
                interimTranscript += event.results[i][0].transcript;
              }
            }

            if (onInterimTranscription) {
              onInterimTranscription(
                finalTranscriptRef.current + interimTranscript,
              );
            }
          };

          recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
            console.error(
              "[VoiceRecorder] ❌ Speech recognition error:",
              event.error,
            );
          };

          recognition.onend = () => {
            console.log(`[VoiceRecorder] 🏁 Speech recognition ended`);
          };

          recognition.start();
          recognitionRef.current = recognition;
          console.log(`[VoiceRecorder] 🎯 Speech recognition started`);
        }
      } else {
        console.log(`[VoiceRecorder] 📡 Using backend method: ${method}`);
      }

      // 2. Setup MediaRecorder for all methods (fallback/persistence)
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = async () => {
        if (isCancelledRef.current) {
          console.log(
            `[VoiceRecorder] 🚫 Recording cancelled, discarding audio.`,
          );
          isCancelledRef.current = false;
          if (streamRef.current) {
            streamRef.current.getTracks().forEach((track) => track.stop());
            streamRef.current = null;
          }
          return;
        }

        console.log(
          `[VoiceRecorder] ⏹️ MediaRecorder stopped, processing audio...`,
        );
        // cleanup stream
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((track) => track.stop());
          streamRef.current = null;
        }

        if (
          false && method === "google-webkit" &&
          recognitionRef.current &&
          finalTranscriptRef.current.trim()
        ) {
          console.log(`[VoiceRecorder] 📝 Using browser transcription result`);
          onTranscriptionComplete({
            text: finalTranscriptRef.current,
            language: language,
          });
        } else if (chunksRef.current.length > 0) {
          console.log(
            `[VoiceRecorder] 📤 Sending audio to backend for processing`,
          );
          const audioBlob = new Blob(chunksRef.current, { type: "audio/wav" });
          await handleTranscription(
            audioBlob,
            method,
            language,
            finalTranscriptRef.current.trim(),
          );
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
      console.log(`[VoiceRecorder] 🎬 Recording started`);
    } catch (err) {
      console.error("[VoiceRecorder] ❌ Error accessing microphone:", err);
      alert(
        "Could not access microphone. Please ensure you have granted permission.",
      );
    }
  }, [onInterimTranscription, onTranscriptionComplete, method, language]);

  const stopRecording = useCallback(() => {
    isCancelledRef.current = false;
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }

    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  }, [isRecording]);

  const cancelRecording = useCallback(() => {
    isCancelledRef.current = true;

    if (recognitionRef.current) {
      recognitionRef.current.stop(); // This triggers onend/result potentially, but we'll ignore it via logic if needed or just let it close
      recognitionRef.current = null;
    }

    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop(); // Triggers onstop, which checks isCancelledRef
      setIsRecording(false);
    }
  }, [isRecording]);

  const handleTranscription = async (
    blob: Blob,
    method: string,
    language?: string,
    browserFallbackText?: string,
  ) => {
    console.log(
      `[VoiceRecorder] 🔄 Starting backend transcription with method: ${method} (Lang: ${language})`,
    );
    console.log(`[VoiceRecorder] 📊 Audio blob size: ${blob.size} bytes`);

    setIsLoading(true);
    try {
      console.log(
        `[VoiceRecorder] 📡 Sending to backend: ${import.meta.env.VITE_API_URL}/api/transcribe`,
      );

      const response = await transcribeApi.transcribeAudio(
        blob,
        method,
        language,
      );

      console.log(`[VoiceRecorder] ✅ Backend transcription completed`);

      if (response.data.text) {
        console.log(
          `[VoiceRecorder] 📝 Transcription result: ${response.data.text.length} characters`,
        );
        onTranscriptionComplete({
          text: response.data.originalText || response.data.text,
          language: response.data.language,
        });
      }
    } catch (err) {
      if (method === "google-webkit" && browserFallbackText) {
        console.log("[VoiceRecorder] Falling back to browser transcription");
        onTranscriptionComplete({
          text: browserFallbackText,
          language: language,
        });
      }
      console.error("[VoiceRecorder] ❌ Failed to transcribe audio:", err);
    } finally {
      setIsLoading(false);
      console.log(`[VoiceRecorder] 🏁 Transcription process finished`);
    }
  };

  return {
    isRecording,
    isLoading,
    startRecording,
    stopRecording,
    cancelRecording,
  };
};
