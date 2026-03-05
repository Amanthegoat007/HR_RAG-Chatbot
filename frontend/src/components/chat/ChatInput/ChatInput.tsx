import {
  Textarea,
  Group,
  ActionIcon,
  Paper,
  Tooltip,
  Box,
  Text,
  Loader,
} from "@mantine/core";
import {
  TbPlayerStopFilled,
  TbMicrophone,
  TbPaperclip,
  TbX,
  TbCheck,
  TbArrowUpRight,
  TbSearch,
} from "react-icons/tb";
import { IoSend } from "react-icons/io5";
// import { MdSavedSearch } from "react-icons/md";
// import { BsSoundwave } from "react-icons/bs";
// import { GoLightBulb } from "react-icons/go";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import {
  MAX_CONVERSATION_TITLE_LENGTH,
  MAX_FILE_UPLOAD_SIZE_MB,
  MAX_FILE_UPLOAD_SIZE_BYTES,
} from "@/config/constants";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  streamMessage,
  addUserMessage,
  createConversation,
  addAssistantLoading,
  setActiveConversation,
  stopMessage,
} from "@/store/slices/chatSlice";
import { ocrApi } from "@/services/api";
import { ragService } from "@/services/ragService";
import { audioManager } from "@/utils/audioManager";

interface ChatInputProps {
  isHeroMode?: boolean;
}

import { requestManager } from "@/utils/requestManager";
import { generateUUID } from "@/utils/uuid";

const activeRequests = requestManager;

export default function ChatInput({ isHeroMode = false }: ChatInputProps) {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [ocrText, setOcrText] = useState<string>("");
  const [isProcessingOcr, setIsProcessingOcr] = useState(false);

  const pendingThunkRef = useRef<{ abort: () => void } | null>(null);

  const { activeConversationId, draftMessageMode, sendingConversationIds } =
    useAppSelector((s) => s.chat);

  const isCurrentSending = activeConversationId
    ? sendingConversationIds.includes(activeConversationId)
    : false;

  const [baseValue, setBaseValue] = useState("");
  const { primaryLanguage, speechRecognitionMethod } = useAppSelector(
    (s) => s.settings,
  );

  const { roles } = useAppSelector((s) => s.auth);
  const isAdmin =
    roles.includes("ROLE_ADMIN") || roles.includes("ROLE_ADMINISTRATOR");
  const {
    isRecording,
    isLoading: isTranscribing,
    startRecording,
    stopRecording,
    cancelRecording,
  } = useVoiceRecorder(
    ({ text, language }) => {
      console.log(
        `[ChatInput] 🎤 Transcription completed: ${text.length} characters (Lang: ${language || primaryLanguage})`,
      );
      const newValue = baseValue ? `${baseValue.trim()} ${text}` : text;
      setValue(newValue);
      inputRef.current?.focus();
    },
    (interimText) => {
      const newValue = baseValue
        ? `${baseValue.trim()} ${interimText}`
        : interimText;
      setValue(newValue);
    },
    speechRecognitionMethod,
    primaryLanguage,
  );
  const DEFAULT_SUGGESTIONS = [
    "What is the onboarding process for new employees?",
    "Can you explain the remote work policy?",
    "How do I request paid time off (PTO)?",
    "What are the core company values?",
    "What is the policy for expense reimbursement?",
  ];

  const [showSuggestions, setShowSuggestions] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);

  useEffect(() => {
    if (
      isFocused &&
      value.trim().length >= 0 &&
      !isCurrentSending &&
      !isRecording &&
      !suggestionsDismissed
    ) {
      setShowSuggestions(true);
    } else {
      setShowSuggestions(false);
    }
  }, [isFocused, value, isCurrentSending, isRecording, suggestionsDismissed]);
  const handleSuggestionClick = (suggestion: string) => {
    setShowSuggestions(false);
    handleSend(suggestion);
  };
  const handleToggleRecording = () => {
    if (isRecording) {
      cancelRecording();
    } else {
      setBaseValue(value);
      startRecording();
    }
  };

  const handleStop = () => {
    if (!isCurrentSending) return;

    // Stop any playing TTS audio
    audioManager.stopAudio();

    if (activeConversationId) {
      if (activeConversationId) {
        activeRequests.abort(activeConversationId);
      }
    }

    if (pendingThunkRef.current) {
      pendingThunkRef.current.abort();
      pendingThunkRef.current = null;
    }

    if (activeConversationId) {
      dispatch(stopMessage(activeConversationId));
    }
  };

  const handleSend = async (overrideMessage?: string) => {
    if (isCurrentSending) {
      handleStop();
      return;
    }

    if (isRecording) {
      stopRecording();
    }

    const messageContent =
      overrideMessage !== undefined ? overrideMessage.trim() : value.trim();
    // Allow sending if text exists OR if we have a file uploaded (ocrText acts as "uploaded" flag now)
    if (!messageContent && !ocrText) return;

    // For RAG, we DO NOT append the huge text to the message. The file is in the DB.
    // We just send the user's question.
    // If message is empty but file is attached, default to "Analyze this file"
    const finalMessage =
      messageContent || `Analyze the uploaded file: ${selectedFile?.name}`;

    setValue("");
    setOcrText("");
    setSelectedFile(null);
    setSuggestionsDismissed(true);

    let targetConvoId = activeConversationId;

    try {
      if (draftMessageMode) {
        const derivedTitle =
          messageContent.trim() ||
          (selectedFile ? `File: ${selectedFile.name}` : "") ||
          (ocrText ? ocrText.slice(0, MAX_CONVERSATION_TITLE_LENGTH) : "") ||
          "New Chat";
        const convo = await dispatch(
          createConversation(
            derivedTitle.slice(0, MAX_CONVERSATION_TITLE_LENGTH),
          ),
        ).unwrap();
        dispatch(setActiveConversation(convo.id));
        targetConvoId = convo.id;
        // Navigate to the conversation URL
        navigate(`/copilot/c/${convo.id}`, { replace: true });
      }
      if (targetConvoId) {
        const optimisticId = generateUUID();
        dispatch(
          addUserMessage({
            id: optimisticId, // Pass the ID here
            text: finalMessage,
            attachment: selectedFile ? { name: selectedFile.name } : undefined,
          }),
        );
        // Note: addAssistantLoading() is no longer needed here.
        // streamMessage dispatches chatSlice.actions.startStreaming() which adds
        // a loading:true streaming message directly.
        const streamPromise = dispatch(
          streamMessage({
            conversationId: targetConvoId,
            message: finalMessage,
            optimisticId,
            language: primaryLanguage,
          }),
        );

        // No need to reset global language
        pendingThunkRef.current = { abort: () => {} }; // streamMessage handles its own abort
        activeRequests.register(targetConvoId, () => {});

        await streamPromise;
      }
    } catch (err) {
      if (err && typeof err === "object" && "name" in err) {
        const error = err as { name: string; message?: string };
        if (
          error.name !== "AbortError" &&
          error.message !== "Aborted" &&
          error.message !== "Request cancelled"
        ) {
          console.error("Failed to send message:", err);
        }
      } else {
        console.error("Failed to send message:", err);
      }
    } finally {
      pendingThunkRef.current = null;
      if (targetConvoId) {
        activeRequests.unregister(targetConvoId);
      }
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // --- File Size Check ---
      if (file.size > MAX_FILE_UPLOAD_SIZE_BYTES) {
        alert(
          `File is too large (${(file.size / (1024 * 1024)).toFixed(1)}MB). Maximum allowed size is ${MAX_FILE_UPLOAD_SIZE_MB}MB.`,
        );
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
        return;
      }

      setSelectedFile(file);
      setIsProcessingOcr(true);
      setOcrText(""); // Clear previous text, we don't use this for RAG anymore

      try {
        let conversationId = activeConversationId;

        // If no active conversation (New Chat), create one strictly for the upload
        if (!conversationId) {
          const derivedTitle = `File: ${file.name}`; // Simple title
          const convo = await dispatch(
            createConversation(
              derivedTitle.slice(0, MAX_CONVERSATION_TITLE_LENGTH),
            ),
          ).unwrap();

          // Set as active and navigate
          dispatch(setActiveConversation(convo.id));
          navigate(`/copilot/c/${convo.id}`, { replace: true });
          conversationId = convo.id;
        }

        if (conversationId) {
          console.log(
            `[ChatInput] Uploading file ${file.name} to RAG session ${conversationId}`,
          );
          // Upload to RAG (OCR + Ingestion)
          // Note: ragService now has the size check too, double safety
          const response = await ragService.uploadFileWithOCR(
            file,
            conversationId,
          );

          // We don't need the text back for the message box in RAG mode
          // The backend has indexed it.
          console.log("[ChatInput] RAG Upload Success:", response.data);

          // Just show success state in UI
          setOcrText("File uploaded and processed successfully.");
        }
      } catch (error) {
        console.error("Failed to process file:", error);
        let errorMessage = "Failed to upload file. Please try again.";
        if (error instanceof Error)
          errorMessage = `Upload Failed: ${error.message}`;
        alert(errorMessage);
        setSelectedFile(null); // Reset on error
        if (fileInputRef.current) fileInputRef.current.value = "";
      } finally {
        setIsProcessingOcr(false);
      }
    }
  };
  const removeFile = () => {
    setSelectedFile(null);
    setOcrText("");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };
  return (
    <Paper
      shadow={isHeroMode ? "sm" : "xs"}
      p="md"
      radius="lg"
      style={{
        maxWidth: "100%",
        margin: "0 auto",
        width: "100%",
        backgroundColor: "var(--app-surface)",
        // backgroundColor: '#ffffff',
        border: "1px solid rgba(16, 185, 129, 0.4)",
        // border: '1px solid var(--mantine-color-default-border)',
        position: "relative",
        transition: "250ms cubic-bezier(0.4, 0, 0.2, 1)",
        minHeight: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        style={{ flex: 1, display: "flex", flexDirection: "column" }}
      >
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleFileChange}
          accept="image/*,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint"
        />
        {selectedFile && (
          <Box
            px="sm"
            py="xs"
            mb="xs"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              backgroundColor: "var(--app-surface-hover)",
              borderRadius: "8px",
              border: "1px solid var(--app-border)",
              width: "fit-content",
            }}
          >
            <TbPaperclip size={16} color="var(--mantine-color-brand-6)" />
            <Box style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <Text
                size="sm"
                fw={600}
                style={{ color: "var(--mantine-color-text)" }}
              >
                {selectedFile.name}
              </Text>
              {isProcessingOcr && (
                <Loader size="xs" color="var(--app-accent-primary)" />
              )}
              {!isProcessingOcr && ocrText && (
                <TbCheck size={14} color="var(--app-accent-primary)" />
              )}
            </Box>
            <ActionIcon
              size="xs"
              variant="subtle"
              color="gray"
              onClick={removeFile}
              type="button"
            >
              <TbX size={14} />
            </ActionIcon>
          </Box>
        )}
        <Box style={{ flex: 1, display: "flex" }}>
          <Textarea
            ref={inputRef}
            value={value}
            onChange={(e) => {
              const newVal = e.currentTarget.value;
              setValue(newVal);
              if (newVal === "") {
                // No need to reset global language
              }
              if (suggestionsDismissed) setSuggestionsDismissed(false);
            }}
            placeholder={
              isRecording
                ? "LISTENING"
                : isHeroMode
                  ? "𝗔𝗦𝗞 𝗔𝗡𝗬𝗧𝗛𝗜𝗡𝗚!!"
                  : isCurrentSending
                    ? "Waiting for response..."
                    : "Message..."
            }
            autosize
            minRows={isHeroMode ? 2 : 1}
            maxRows={8}
            variant="unstyled"
            disabled={isCurrentSending}
            style={{ flex: 1, marginTop: 0 }}
            styles={{
              input: {
                padding: "8px 4px",
                fontSize: "16px",
                lineHeight: 1,
                color: "var(--mantine-color-text)",
                backgroundColor: "transparent",
                "&:disabled": {
                  backgroundColor: "transparent",
                  color: "var(--mantine-color-text)",
                  opacity: 1,
                  cursor: "not-allowed",
                },
              },
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            onFocus={() => {
              setIsFocused(true);
              setSuggestionsDismissed(false);
            }}
            onBlur={() => {
              // Delay slightly to allow click event on suggestions to fire first
              setTimeout(() => setIsFocused(false), 200);
            }}
          />
        </Box>
        <Group justify="end" align="center" mt="xs">
          <Group gap="xs">
            {!isRecording && isAdmin && (
              <>
                <Tooltip label="Attach file">
                  <ActionIcon
                    variant="subtle"
                    style={{ color: "var(--mantine-color-text)" }}
                    radius="xl"
                    size="lg"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isProcessingOcr || isCurrentSending}
                    type="button"
                  >
                    <TbPaperclip size={18} />
                  </ActionIcon>
                </Tooltip>
              </>
            )}
            {!isRecording && (
              <Tooltip label={isRecording ? "Stop recording" : "Record voice"}>
                <ActionIcon
                  onClick={handleToggleRecording}
                  style={{
                    color: isRecording ? "red" : "var(--mantine-color-text)",
                    transition: "250ms cubic-bezier(0.4, 0, 0.2, 1)",
                    transform: isRecording ? "scale(1.1)" : "scale(1)",
                  }}
                  variant={isRecording ? "filled" : "subtle"}
                  radius="xl"
                  size="lg"
                  disabled={isCurrentSending || isTranscribing}
                  loading={isTranscribing}
                  type="button"
                >
                  <TbMicrophone size={18} />
                </ActionIcon>
              </Tooltip>
            )}
            {isRecording && (
              <ActionIcon
                onClick={handleToggleRecording}
                variant="filled"
                color="gray.2"
                radius="md"
                size="xl"
                style={{
                  backgroundColor: "var(--mantine-color-gray-2)",
                  color: "var(--mantine-color-text)",
                }}
                type="button"
              >
                <TbPlayerStopFilled stroke="1.5" size={20} />
              </ActionIcon>
            )}
            <Tooltip
              label={
                isCurrentSending
                  ? "Stop generating"
                  : isRecording
                    ? "Finish recording"
                    : "Send message"
              }
            >
              <ActionIcon
                onClick={() => handleSend()}
                color={
                  isCurrentSending
                    ? "red"
                    : isRecording
                      ? "var(--app-accent-primary)"
                      : "var(--app-background-dark)"
                }
                variant="filled"
                radius="md"
                size="xl"
                disabled={
                  (!isCurrentSending &&
                    !isRecording &&
                    !value.trim() &&
                    !ocrText) ||
                  isProcessingOcr
                }
                style={{
                  transition: "250ms cubic-bezier(0.4, 0, 0.2, 1)",
                  boxShadow:
                    !isCurrentSending &&
                    (value.trim() || isRecording || ocrText)
                      ? "0 4px 12px rgba(0, 0, 0, 0.1)"
                      : "none",
                }}
                type="button"
              >
                {isCurrentSending ? (
                  <TbPlayerStopFilled size={20} />
                ) : isRecording ? (
                  <TbCheck size={24} />
                ) : (
                  <IoSend color="white" size={20} />
                )}
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        {showSuggestions && (
          <Box
            style={{
              borderTop: "1px solid var(--app-border)",
              paddingTop: "12px",
              marginTop: "8px",
              display: "flex",
              flexDirection: "column",
              gap: "4px",
              maxHeight: "140px",
              overflowY: "auto",
              paddingRight: "4px",
            }}
          >
            {DEFAULT_SUGGESTIONS.map((suggestion, index) => (
              <Box
                key={index}
                onMouseDown={(e) => {
                  e.preventDefault();
                  handleSuggestionClick(suggestion);
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "10px 12px",
                  borderRadius: "10px",
                  cursor: "pointer",
                  transition: "background-color 0.2s ease",
                  backgroundColor: "transparent",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor =
                    "var(--app-surface-hover)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                <Group
                  gap="sm"
                  wrap="nowrap"
                  align="flex-start"
                  style={{ flex: 1 }}
                >
                  <TbSearch style={{ marginTop: "4px", flexShrink: 0 }} />
                  <Text size="sm" c="dimmed" style={{ flex: 1 }}>
                    {suggestion}
                  </Text>
                </Group>
                <TbArrowUpRight />
              </Box>
            ))}
          </Box>
        )}
      </form>
    </Paper>
  );
}
