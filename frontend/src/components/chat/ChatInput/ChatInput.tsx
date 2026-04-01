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
  TbAlertCircle,
  TbClockHour4,
} from "react-icons/tb";
import { IoSend } from "react-icons/io5";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import ResponseModeControl from "@/components/chat/ResponseModeControl";
import {
  MAX_CONVERSATION_TITLE_LENGTH,
  MAX_FILE_UPLOAD_SIZE_MB,
  MAX_FILE_UPLOAD_SIZE_BYTES,
} from "@/config/constants";
import { documentService } from "@/services/documentService";
import { chatApi } from "@/services/api";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  streamMessage,
  addUserMessage,
  createConversation,
  setActiveConversation,
  stopMessage,
} from "@/store/slices/chatSlice";
import type { ReasoningMode } from "@/types/chat.types";
import { stopSpeaking } from "@/utils/browserSpeechSynthesis";
import { requestManager } from "@/utils/requestManager";
import { generateUUID } from "@/utils/uuid";
import classes from "./ChatInput.module.css";

interface ChatInputProps {
  isHeroMode?: boolean;
}

type AttachmentState = "idle" | "uploading" | "processing" | "ready" | "failed";

const activeRequests = requestManager;
const DEFAULT_FALLBACK_SUGGESTIONS = [
  "What is the onboarding process for new employees?",
  "Can you explain the remote work policy?",
  "How do I request paid time off (PTO)?",
  "What are the core company values?",
  "What is the policy for expense reimbursement?",
];
const DOCUMENT_POLL_INTERVAL_MS = 1500;
const DOCUMENT_POLL_TIMEOUT_MS = 120000;

export default function ChatInput({ isHeroMode = false }: ChatInputProps) {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingThunkRef = useRef<{ abort: () => void } | null>(null);
  const attachmentOpRef = useRef(0);

  const [value, setValue] = useState("");
  const [baseValue, setBaseValue] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [attachedDocumentId, setAttachedDocumentId] = useState<string | null>(null);
  const [attachmentState, setAttachmentState] = useState<AttachmentState>("idle");
  const [attachmentMessage, setAttachmentMessage] = useState<string>("");
  const [reasoningMode, setReasoningMode] = useState<ReasoningMode>("fast");
  const [dynamicSuggestions, setDynamicSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);

  const { activeConversationId, draftMessageMode, sendingConversationIds } =
    useAppSelector((s) => s.chat);
  const { primaryLanguage } = useAppSelector((s) => s.settings);
  const isCurrentSending = activeConversationId
    ? sendingConversationIds.includes(activeConversationId)
    : false;

  const {
    isRecording,
    isLoading: isTranscribing,
    capability: voiceCapability,
    startRecording,
    stopRecording,
    cancelRecording,
  } = useVoiceRecorder(
    ({ text, language }) => {
      const newValue = baseValue ? `${baseValue.trim()} ${text}` : text;
      setValue(newValue);
      setBaseValue("");
      inputRef.current?.focus();
      console.log(
        `[ChatInput] 🎤 Voice input completed: ${text.length} characters (Lang: ${language || primaryLanguage})`,
      );
    },
    (interimText) => {
      const newValue = baseValue
        ? `${baseValue.trim()} ${interimText}`.trim()
        : interimText;
      setValue(newValue);
    },
    primaryLanguage,
  );
  const attachmentReady = attachmentState === "ready";
  const attachmentBusy =
    attachmentState === "uploading" || attachmentState === "processing";
  const hasMessageDraft = Boolean(value.trim() || attachmentReady);
  const isReadyToSend =
    !isCurrentSending && !isRecording && hasMessageDraft && !attachmentBusy;
  const isComposerFocused = isFocused || isRecording;

  useEffect(() => {
    chatApi
      .fetchPopularQuestions()
      .then((data) =>
        setDynamicSuggestions(
          data.length > 0 ? data : DEFAULT_FALLBACK_SUGGESTIONS,
        ),
      )
      .catch((err) => {
        console.error("Failed to fetch popular questions:", err);
        setDynamicSuggestions(DEFAULT_FALLBACK_SUGGESTIONS);
      });
  }, []);

  useEffect(() => {
    const handleStarterPrompt = (event: Event) => {
      const customEvent = event as CustomEvent<{ prompt?: string }>;
      const prompt = customEvent.detail?.prompt?.trim();
      if (!prompt) return;

      setValue(prompt);
      setSuggestionsDismissed(true);
      setShowSuggestions(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    };

    window.addEventListener("copilot:starter-prompt", handleStarterPrompt);
    return () => {
      window.removeEventListener("copilot:starter-prompt", handleStarterPrompt);
    };
  }, []);

  useEffect(() => {
    if (
      isFocused &&
      !isCurrentSending &&
      !isRecording &&
      !suggestionsDismissed
    ) {
      setShowSuggestions(true);
    } else {
      setShowSuggestions(false);
    }
  }, [isFocused, isCurrentSending, isRecording, suggestionsDismissed]);

  const resetAttachment = () => {
    setSelectedFile(null);
    setAttachedDocumentId(null);
    setAttachmentState("idle");
    setAttachmentMessage("");
    attachmentOpRef.current += 1;
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const waitForDocumentReady = async (
    documentId: string,
    operationId: number,
  ) => {
    const startedAt = Date.now();

    while (Date.now() - startedAt < DOCUMENT_POLL_TIMEOUT_MS) {
      const doc = await documentService.getDocument(documentId);
      if (attachmentOpRef.current !== operationId) {
        return null;
      }

      if (doc.status === "ready") {
        return doc;
      }
      if (doc.status === "failed") {
        throw new Error(doc.error_message || "Document processing failed.");
      }

      setAttachmentState("processing");
      setAttachmentMessage("Processing document for this conversation...");
      await new Promise((resolve) =>
        window.setTimeout(resolve, DOCUMENT_POLL_INTERVAL_MS),
      );
    }

    throw new Error("Document processing timed out. Please try again.");
  };

  const ensureConversationForAttachment = async (
    fileName: string,
  ): Promise<string> => {
    if (activeConversationId) {
      return activeConversationId;
    }

    const derivedTitle = `File: ${fileName}`.slice(
      0,
      MAX_CONVERSATION_TITLE_LENGTH,
    );
    const convo = await dispatch(createConversation(derivedTitle)).unwrap();
    dispatch(setActiveConversation(convo.id));
    navigate(`/copilot/c/${convo.id}`, { replace: true });
    return convo.id;
  };

  const removeFile = async () => {
    attachmentOpRef.current += 1;
    const documentId = attachedDocumentId;
    resetAttachment();

    if (!documentId) return;
    try {
      await documentService.deleteDocument(documentId);
    } catch (error) {
      console.warn("Failed to remove attached document from session", error);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_FILE_UPLOAD_SIZE_BYTES) {
      setAttachmentState("failed");
      setAttachmentMessage(
        `File is too large (${(file.size / (1024 * 1024)).toFixed(1)}MB). Maximum allowed size is ${MAX_FILE_UPLOAD_SIZE_MB}MB.`,
      );
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    attachmentOpRef.current += 1;
    const operationId = attachmentOpRef.current;
    setSelectedFile(file);
    setAttachedDocumentId(null);
    setAttachmentState("uploading");
    setAttachmentMessage("Uploading document to this conversation...");

    try {
      const conversationId = await ensureConversationForAttachment(file.name);
      if (attachmentOpRef.current !== operationId) {
        return;
      }

      const job = await documentService.uploadDocument(file, {
        scope: "session",
        conversationId,
      });
      if (attachmentOpRef.current !== operationId) {
        return;
      }

      setAttachedDocumentId(job.document_id);
      setAttachmentState(job.status === "ready" ? "ready" : "processing");
      setAttachmentMessage("Processing document for this conversation...");

      const readyDocument = await waitForDocumentReady(job.document_id, operationId);
      if (!readyDocument || attachmentOpRef.current !== operationId) {
        return;
      }

      setAttachmentState("ready");
      setAttachmentMessage("Document ready for this conversation.");
    } catch (error) {
      if (attachmentOpRef.current !== operationId) {
        return;
      }
      console.error("Failed to upload session document:", error);
      setAttachmentState("failed");
      setAttachmentMessage(
        error instanceof Error
          ? error.message
          : "Failed to upload file. Please try again.",
      );
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setShowSuggestions(false);
    handleSend(suggestion);
  };

  const handleToggleRecording = () => {
    if (isRecording) {
      cancelRecording();
      return;
    }

    stopSpeaking();
    setBaseValue(value);
    startRecording();
  };

  const handleStop = () => {
    if (!isCurrentSending) return;

    stopSpeaking();

    if (activeConversationId) {
      activeRequests.abort(activeConversationId);
    }

    if (pendingThunkRef.current) {
      pendingThunkRef.current.abort();
      pendingThunkRef.current = null;
    }

    if (activeConversationId) {
      dispatch(stopMessage(activeConversationId));
    }
    setReasoningMode("fast");
  };

  const handleSend = async (overrideMessage?: string) => {
    if (isCurrentSending) {
      handleStop();
      return;
    }

    if (isRecording) {
      stopRecording();
      return;
    }

    if (attachmentBusy) {
      return;
    }

    const messageContent =
      overrideMessage !== undefined ? overrideMessage.trim() : value.trim();
    if (!messageContent && !attachmentReady) return;

    const finalMessage =
      messageContent || `Analyze the uploaded file: ${selectedFile?.name}`;
    const selectedReasoningMode = reasoningMode;
    const activeAttachmentDocumentId = attachmentReady ? attachedDocumentId || undefined : undefined;

    setValue("");
    setSuggestionsDismissed(true);

    let targetConvoId = activeConversationId;

    try {
      if (draftMessageMode) {
        const derivedTitle =
          messageContent ||
          (selectedFile ? `File: ${selectedFile.name}` : "") ||
          "New Chat";
        const convo = await dispatch(
          createConversation(
            derivedTitle.slice(0, MAX_CONVERSATION_TITLE_LENGTH),
          ),
        ).unwrap();
        dispatch(setActiveConversation(convo.id));
        targetConvoId = convo.id;
        navigate(`/copilot/c/${convo.id}`, { replace: true });
      }

      if (targetConvoId) {
        const optimisticId = generateUUID();
        dispatch(
          addUserMessage({
            id: optimisticId,
            text: finalMessage,
            attachment: selectedFile ? { name: selectedFile.name } : undefined,
          }),
        );

        const streamPromise = dispatch(
          streamMessage({
            conversationId: targetConvoId,
            message: finalMessage,
            optimisticId,
            language: primaryLanguage,
            reasoningMode: selectedReasoningMode,
            activeAttachmentDocumentId,
          }),
        );

        pendingThunkRef.current = { abort: () => {} };
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
      setReasoningMode("fast");
      if (targetConvoId) {
        activeRequests.unregister(targetConvoId);
      }
      if (attachmentReady) {
        resetAttachment();
      }
    }
  };

  const suggestionsToDisplay =
    dynamicSuggestions.length > 0
      ? dynamicSuggestions
      : DEFAULT_FALLBACK_SUGGESTIONS;
  const attachmentTone =
    attachmentState === "failed"
      ? "error"
      : attachmentState === "ready"
        ? "success"
        : "neutral";

  return (
    <Paper
      shadow={isHeroMode ? "sm" : "xs"}
      p={isHeroMode ? "sm" : "md"}
      radius="lg"
      className={`${classes.inputContainer} ${
        isHeroMode ? classes.inputContainerHero : ""
      } ${isComposerFocused ? classes.inputContainerFocused : ""} ${
        isReadyToSend ? classes.inputContainerReady : ""
      }`}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void handleSend();
        }}
        className={`${classes.composerForm} ${
          isHeroMode ? classes.composerFormHero : ""
        }`}
      >
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleFileChange}
          accept="image/*,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint"
        />

        {selectedFile && (
          <Box px="sm" py="xs" className={classes.fileAttachment}>
            <TbPaperclip size={16} color="var(--app-accent-primary)" />
            <Box className={classes.fileAttachmentInner}>
              <Text
                size="sm"
                fw={600}
                truncate
                style={{ color: "var(--mantine-color-text)", minWidth: 0 }}
              >
                {selectedFile.name}
              </Text>
              {attachmentState === "uploading" || attachmentState === "processing" ? (
                <Loader size="xs" color="var(--app-accent-primary)" />
              ) : null}
              {attachmentState === "ready" ? (
                <TbCheck size={14} color="var(--app-accent-primary)" />
              ) : null}
              {attachmentState === "failed" ? (
                <TbAlertCircle size={14} color="var(--mantine-color-red-6)" />
              ) : null}
            </Box>
            <ActionIcon
              size="xs"
              variant="subtle"
              color="gray"
              onClick={() => {
                void removeFile();
              }}
              type="button"
            >
              <TbX size={14} />
            </ActionIcon>
          </Box>
        )}

        {selectedFile && attachmentMessage ? (
          <Text
            size="xs"
            px="xs"
            className={
              attachmentTone === "error"
                ? classes.attachmentMessageError
                : attachmentTone === "success"
                  ? classes.attachmentMessageSuccess
                  : classes.attachmentMessage
            }
          >
            {attachmentMessage}
          </Text>
        ) : null}

        <Box className={classes.textareaWrapper}>
          <Textarea
            ref={inputRef}
            value={value}
            onChange={(e) => {
              const newVal = e.currentTarget.value;
              setValue(newVal);
              if (suggestionsDismissed) setSuggestionsDismissed(false);
            }}
            placeholder={
              isRecording
                ? "Listening…"
                : isHeroMode
                  ? "Ask about leave, benefits, medical, payroll, or policy..."
                  : isCurrentSending
                    ? "Waiting for response..."
                    : "Message..."
            }
            autosize
            minRows={1}
            maxRows={8}
            variant="unstyled"
            disabled={isCurrentSending}
            className={classes.textareaInput}
            styles={{
              input: {
                padding: "10px 4px 6px",
                fontSize: "16px",
                lineHeight: 1.5,
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
                void handleSend();
              }
            }}
            onFocus={() => {
              setIsFocused(true);
              setSuggestionsDismissed(false);
            }}
            onBlur={() => {
              window.setTimeout(() => setIsFocused(false), 200);
            }}
          />
        </Box>

        <div className={classes.actionRow}>
          <ResponseModeControl
            value={reasoningMode}
            onChange={setReasoningMode}
            disabled={isCurrentSending || attachmentBusy}
          />
          <Group gap="xs" className={classes.actionButtons}>
            {!isRecording && (
              <Tooltip label="Attach file to this conversation">
                <ActionIcon
                  variant="subtle"
                  className={classes.utilityActionButton}
                  radius="xl"
                  size="lg"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={attachmentBusy || isCurrentSending}
                  type="button"
                >
                  <TbPaperclip size={18} />
                </ActionIcon>
              </Tooltip>
            )}

            {!isRecording && (
              <Tooltip label={voiceCapability.message || "Record voice"}>
                <ActionIcon
                  onClick={handleToggleRecording}
                  className={`${classes.utilityActionButton} ${
                    isRecording ? classes.utilityActionButtonRecording : ""
                  }`}
                  variant={isRecording ? "filled" : "subtle"}
                  radius="xl"
                  size="lg"
                  disabled={
                    isCurrentSending ||
                    isTranscribing ||
                    !voiceCapability.supported
                  }
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
                    : attachmentBusy
                      ? "Waiting for attachment processing"
                      : "Send message"
              }
            >
              <ActionIcon
                onClick={() => {
                  void handleSend();
                }}
                variant="filled"
                radius="md"
                size="xl"
                disabled={
                  (!isCurrentSending &&
                    !isRecording &&
                    !value.trim() &&
                    !attachmentReady) ||
                  attachmentBusy
                }
                className={`${classes.sendButton} ${
                  isCurrentSending
                    ? classes.sendButtonStop
                    : isRecording
                      ? classes.sendButtonRecording
                      : isReadyToSend
                        ? classes.sendButtonReady
                        : ""
                }`}
                type="button"
              >
                {isCurrentSending ? (
                  <TbPlayerStopFilled size={20} />
                ) : isRecording ? (
                  <TbCheck size={24} />
                ) : attachmentBusy ? (
                  <TbClockHour4 size={20} />
                ) : (
                  <IoSend color="white" size={20} />
                )}
              </ActionIcon>
            </Tooltip>
          </Group>
        </div>

        {!voiceCapability.supported && voiceCapability.message ? (
          <Group gap={6} className={classes.voiceGuidance}>
            <TbAlertCircle size={14} />
            <Text size="xs">{voiceCapability.message}</Text>
          </Group>
        ) : null}

        {showSuggestions && (
          <Box className={classes.suggestionBox}>
            {suggestionsToDisplay.map((suggestion, index) => (
              <Box
                key={index}
                onMouseDown={(e) => {
                  e.preventDefault();
                  handleSuggestionClick(suggestion);
                }}
                className={classes.suggestionItem}
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
