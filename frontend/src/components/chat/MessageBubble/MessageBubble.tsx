import {
  Paper,
  Text,
  Loader,
  Box,
  Alert,
  Group,
  ActionIcon,
  Stack,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  TbAlertCircle,
  TbCopy,
  TbRefresh,
  TbCornerDownRight,
  TbFileDescription,
  TbCheck,
  TbVolume,
  TbPlayerStopFilled,
} from "react-icons/tb";
import { useMemo, useState } from "react";
import { useClipboard } from "@mantine/hooks";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ttsApi } from "@/services/api";
import { audioManager } from "@/utils/audioManager";

import { parseMessageContent } from "@/utils/contentParser";
import { ChatTable } from "../ChatTable";
import { ChatChart } from "../ChatChart";
import { ChatDataView } from "../ChatDataView";
import type { ChartData, TableData, DataViewData } from "@/utils/contentParser";
import { TbFileDescription as TbSourceIcon } from "react-icons/tb";

import type { MessageBubbleProps } from "./MessageBubble.types";
import classes from "./MessageBubble.module.css";

// ── Source Citation Extraction ─────────────────────────────────────
interface SourceCitation {
  filename: string;
  detail: string; // page/section info
}

function normalizeAssistantMarkdown(rawText: string): string {
  return rawText
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/([.!?])\s+(\d+\.\s+)/g, "$1\n\n$2")
    .replace(/(\d+\.)\s+—\s+/g, "$1 ")
    .trim();
}

/**
 * Extracts source citations from LLM text in various formats:
 *   - (Source: file | Section: X | Page: Y)
 *   - (Source: file | Section: X | Page: Y, title)
 *   - (Source: file, Page X)
 *   - (Source: file)
 * Returns the cleaned text and deduplicated citations.
 */
function extractSourceCitations(text: string): {
  cleanText: string;
  citations: SourceCitation[];
} {
  const citations: SourceCitation[] = [];
  const seen = new Set<string>();

  // Match (Source: ...) with balanced parentheses support
  // Use a greedy match that finds "(Source:" and captures until the LAST ")"
  // that balances the opening "("
  const matches: { full: string; inner: string; index: number }[] = [];
  const startPattern = /\(Source:\s*/gi;
  let startMatch;

  while ((startMatch = startPattern.exec(text)) !== null) {
    // Find the balanced closing paren
    let depth = 1;
    let pos = startMatch.index + startMatch[0].length;
    while (pos < text.length && depth > 0) {
      if (text[pos] === "(") depth++;
      if (text[pos] === ")") depth--;
      pos++;
    }
    if (depth === 0) {
      const full = text.substring(startMatch.index, pos);
      const inner = text.substring(
        startMatch.index + startMatch[0].length,
        pos - 1,
      );
      matches.push({ full, inner, index: startMatch.index });
    }
  }

  for (const m of matches) {
    const inner = m.inner.trim();

    // Parse pipe-separated format: "file | Section: X | Page: Y, title"
    if (inner.includes("|")) {
      const parts = inner.split("|").map((p) => p.trim());
      const filename = parts[0] || "Unknown";
      const details = parts
        .slice(1)
        .map((p) => p.replace(/^(Section|Page):\s*/i, "").trim())
        .filter((p) => p && p !== "Unknown Section" && p !== "?")
        .join(", ");
      const key = `${filename}|${details}`;
      if (!seen.has(key)) {
        seen.add(key);
        citations.push({ filename, detail: details });
      }
    } else {
      // Simple format: "filename, Page X" or just "filename"
      const commaIdx = inner.indexOf(",");
      const filename =
        commaIdx > -1 ? inner.substring(0, commaIdx).trim() : inner;
      const detail = commaIdx > -1 ? inner.substring(commaIdx + 1).trim() : "";
      const key = `${filename}|${detail}`;
      if (!seen.has(key)) {
        seen.add(key);
        citations.push({ filename, detail });
      }
    }
  }

  // Remove all matched citation strings from text
  let cleanText = text;
  for (const m of matches.reverse()) {
    cleanText =
      cleanText.substring(0, m.index) +
      cleanText.substring(m.index + m.full.length);
  }
  cleanText = cleanText
    .replace(/\s{2,}/g, " ")
    .replace(/\.\s*\./g, ".")
    .trim();

  return { cleanText, citations };
}

/** Renders a single source citation chip */
function SourceChip({ citation }: { citation: SourceCitation }) {
  const label = citation.detail
    ? `${citation.filename} · ${citation.detail}`
    : citation.filename;

  return (
    <span className={classes.sourceChip}>
      <TbSourceIcon className={classes.sourceChipIcon} />
      <span className={classes.sourceChipText}>{label}</span>
    </span>
  );
}

/** Renders the sources panel with expandable cards below the answer */
function SourcesPanel({
  citations,
  enrichedSources,
}: {
  citations: SourceCitation[];
  enrichedSources?: any[];
}) {
  // Prefer enriched sources from backend (have chunk text) over citation extraction
  const hasEnriched = enrichedSources && enrichedSources.length > 0;
  const items = hasEnriched ? enrichedSources : citations;
  if (!items || items.length === 0) return null;

  return (
    <div className={classes.sourcesPanel}>
      <div className={classes.sourcesLabel}>
        <TbSourceIcon size={12} />
        Sources ({items.length})
      </div>
      <div>
        {hasEnriched
          ? enrichedSources!.map((src: any, i: number) => (
              <ExpandableSourceCard key={i} source={src} />
            ))
          : citations.map((c, i) => <SourceChip key={i} citation={c} />)}
      </div>
    </div>
  );
}

/** Expandable source card showing filename + chunk text on expand */
function ExpandableSourceCard({ source }: { source: any }) {
  const [expanded, setExpanded] = useState(false);
  const filename = source.filename || "Unknown";
  const section =
    source.section && source.section !== "Unknown Section"
      ? source.section
      : "";
  const page = source.page_number || "";
  const score = source.score ? `${Math.round(source.score * 100)}%` : "";
  const text = source.text || "";

  const detail = [
    section,
    page ? `Page ${page}` : "",
    score ? `Relevance: ${score}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className={`${classes.sourceCard} ${expanded ? classes.sourceCardExpanded : ""}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className={classes.sourceCardHeader}>
        <TbSourceIcon className={classes.sourceChipIcon} />
        <div className={classes.sourceCardTitle}>
          <span className={classes.sourceCardFilename}>{filename}</span>
          {detail && <span className={classes.sourceCardDetail}>{detail}</span>}
        </div>
        <span className={classes.sourceCardToggle}>{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && text && (
        <div className={classes.sourceCardBody}>
          <Text
            size="sm"
            c="var(--app-text-secondary)"
            style={{ lineHeight: 1.6, whiteSpace: "pre-wrap" }}
          >
            {text}
          </Text>
        </div>
      )}
    </div>
  );
}

/** Pipeline stage indicator — shows during loading/streaming */
function PipelineStageIndicator({ stages }: { stages: any[] }) {
  if (!stages || stages.length === 0) return null;
  const allStages = [
    { id: "embedding", icon: "🔍", defaultLabel: "Embedding query..." },
    { id: "searching", icon: "📚", defaultLabel: "Searching documents..." },
    { id: "reranking", icon: "⚡", defaultLabel: "Reranking results..." },
    { id: "generating", icon: "✨", defaultLabel: "Generating response..." },
  ];

  return (
    <div className={classes.stageIndicator}>
      {allStages.map((def) => {
        const stage = stages.find((s: any) => s.stage === def.id);
        const status = stage?.status || "pending";
        return (
          <div
            key={def.id}
            className={`${classes.stageItem} ${classes[`stage_${status}`] || ""}`}
          >
            <span className={classes.stageDot}>
              {status === "done" ? "✓" : status === "active" ? def.icon : "○"}
            </span>
            <span className={classes.stageLabel}>
              {stage?.label || def.defaultLabel}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const markdownComponents = {
  table: ({ node, ...props }: any) => (
    <table className={classes.table} {...props} />
  ),
  th: ({ node, ...props }: any) => <th className={classes.th} {...props} />,
  td: ({ node, ...props }: any) => <td className={classes.td} {...props} />,
};

const FileCard = ({ name }: { name: string }) => (
  <Paper
    withBorder
    p="sm"
    radius="md"
    my="sm"
    style={{
      backgroundColor: "var(--app-surface-hover)",
      borderColor: "var(--app-border)",
      display: "flex",
      alignItems: "center",
      gap: "12px",
      maxWidth: "300px",
      cursor: "default",
      transition: "transform 0.2s ease",
    }}
  >
    <Box
      style={{
        width: "40px",
        height: "40px",
        borderRadius: "8px",
        backgroundColor: "var(--app-surface)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--app-accent-primary)",
      }}
    >
      <TbFileDescription size={24} />
    </Box>
    <Box style={{ flex: 1, overflow: "hidden" }}>
      <Text size="sm" fw={600} truncate c="var(--app-text-primary)">
        {name}
      </Text>
      <Text size="xs" c="var(--app-text-secondary)">
        File Attachment
      </Text>
    </Box>
  </Paper>
);

export default function MessageBubble({
  role,
  content: text,
  loading,
  attachment,
  onRefresh,
  stages,
  sources,
}: MessageBubbleProps) {
  const isUser = role === "user";

  // Parse structured data if assistant
  const content = useMemo(() => {
    return parseMessageContent(text, isUser);
  }, [text, isUser]);

  // Parse hidden sources from DB-persisted content (<!-- SOURCES_JSON:[...] -->)
  const { displayText, dbSources } = useMemo(() => {
    const sourcesMatch = text?.match(/<!-- SOURCES_JSON:(.*?) -->/);
    if (sourcesMatch) {
      try {
        const parsed = JSON.parse(sourcesMatch[1]);
        const clean = text.replace(/\n?<!-- SOURCES_JSON:.*? -->/, "").trim();
        return { displayText: clean, dbSources: parsed };
      } catch {
        /* ignore parse errors */
      }
    }
    return { displayText: text, dbSources: null };
  }, [text]);

  // Merge: prefer SSE sources (live), fall back to DB sources (after refresh)
  const effectiveSources = sources && sources.length > 0 ? sources : dbSources;

  const clipboard = useClipboard({ timeout: 2000 });

  const getCopyableText = () => {
    const attachmentRegex =
      /\[(?:Extracted from|Uploaded File|Attached):?\s*(.*?)\]:?/g;
    // Strip the attachment marker AND everything that follows it (OCR text)
    const index = content.text.search(attachmentRegex);
    if (index !== -1) {
      return content.text.substring(0, index).trim();
    }
    return content.text.trim();
  };

  const [playing, setPlaying] = useState(false);

  const handleSpeak = async () => {
    if (playing) {
      // Stop currently playing audio
      audioManager.stopAudio();
      setPlaying(false);
      return;
    }

    try {
      setPlaying(true);
      const language = content.extras?.language || "en";
      const response = await ttsApi.synthesizeText(content.text, language);

      const audioBlob = response.data;
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);

      // Register with global audio manager
      audioManager.setAudio(audio, audioUrl);

      audio.onended = () => {
        setPlaying(false);
        audioManager.clearAudio();
      };

      audio.onerror = () => {
        setPlaying(false);
        audioManager.clearAudio();
      };

      await audio.play();
    } catch (error) {
      console.error("Playback failed:", error);
      setPlaying(false);
      audioManager.clearAudio();
    }
  };

  if (loading) {
    return (
      <Box
        style={{
          alignSelf: "flex-start",
          paddingLeft: 8,
          paddingTop: 4,
        }}
      >
        {stages && stages.length > 0 ? (
          <>
            <PipelineStageIndicator stages={stages} />
            <Loader type="dots" size="sm" mt={8} />
          </>
        ) : (
          <Loader type="dots" size="sm" />
        )}
      </Box>
    );
  }

  // Handle error messages
  const isError =
    content.type === "error" || content.text.toLowerCase().includes("error");

  return (
    <Paper
      shadow="xs"
      px="md"
      radius="lg"
      withBorder={!isUser}
      style={{
        alignSelf: isUser ? "flex-end" : "flex-start",
        maxWidth: "80%",
        width: isUser ? "fit-content" : "100%",
        background: isUser ? "var(--app-surface)" : "transparent",
        color: isUser ? "var(--app-text-primary)" : "inherit",
        border: isUser ? "1px solid var(--app-border)" : "none",
        transition: "250ms cubic-bezier(0.4, 0, 0.2, 1)",
        boxShadow: isUser ? "var(--app-shadow-sm)" : "none",
        animation: "slideUp 0.3s ease-out",
        display: "flex",
        gap: "12px",
        alignItems: "flex-start",
        overflowWrap: "break-word",
        wordBreak: "break-word",
      }}
    >
      {!isUser && (
        <Box
          style={{
            width: 20,
            height: 20,
            borderRadius: "50%",
            marginTop: 20,
            flexShrink: 0,
            background:
              "linear-gradient(135deg, var(--app-accent-primary) 0%, var(--app-accent-secondary) 100%)",
          }}
        />
      )}
      <Box style={{ flex: 1, minWidth: 0, width: "100%" }}>
        {!isUser && content.extras?.title && (
          <Title
            order={4}
            mb="xs"
            c="var(--app-text-primary)"
            style={{ fontWeight: 600 }}
          >
            {content.extras.title}
          </Title>
        )}

        <Box>
          {/* Display explicit attachment if present */}
          {attachment && <FileCard name={attachment.name} />}

          {(() => {
            // Handle blocks format (Standard format for assistant)
            if (content.type === "blocks" && content.blocks) {
              return (
                <Stack gap="md">
                  {content.blocks.map((block, index) => {
                    switch (block.type) {
                      case "text": {
                        const normalizedBlockMarkdown =
                          normalizeAssistantMarkdown(block.content || "");
                        return (
                          <Box
                            key={index}
                            className={classes.markdownContent}
                            style={{
                              fontSize: "var(--mantine-font-size-lg)",
                              lineHeight: 1.6,
                            }}
                          >
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={markdownComponents}
                            >
                              {normalizedBlockMarkdown}
                            </ReactMarkdown>
                          </Box>
                        );
                      }
                      case "table":
                        return (
                          <ChatTable
                            key={index}
                            data={block.data as TableData}
                          />
                        );
                      case "chart":
                        return (
                          <ChatChart
                            key={index}
                            data={block.data as ChartData}
                          />
                        );
                      case "data_view":
                        return (
                          <ChatDataView
                            key={index}
                            data={block.data as DataViewData}
                          />
                        );
                      default:
                        return null;
                    }
                  })}
                </Stack>
              );
            }

            // Handle plain text (Default for user or fallback)
            // Handle mixed text with attachments if present in raw text
            const attachmentRegex =
              /\[(?:Extracted from|Uploaded File|Attached):?\s*(.*?)\]:?/g;
            const match = attachmentRegex.exec(content.text);
            if (match) {
              const fileName = match[1];
              // Strip the attachment marker AND everything that follows it (OCR text)
              const markerIndex = content.text.search(attachmentRegex);
              const cleanText = content.text.substring(0, markerIndex).trim();
              return (
                <>
                  {!attachment && <FileCard name={fileName} />}
                  {cleanText && (
                    <Box
                      className={classes.markdownContent}
                      style={{
                        fontSize: "var(--mantine-font-size-lg)",
                        lineHeight: 1.6,
                      }}
                    >
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={markdownComponents}
                      >
                        {cleanText}
                      </ReactMarkdown>
                    </Box>
                  )}
                </>
              );
            }

            // For assistant messages: extract source citations
            const textForParsing = !isUser
              ? displayText || content.text
              : content.text;
            const { cleanText: answerText, citations } = !isUser
              ? extractSourceCitations(textForParsing)
              : { cleanText: textForParsing, citations: [] };
            const markdownText = !isUser
              ? normalizeAssistantMarkdown(answerText)
              : answerText;

            return (
              <>
                <Box
                  className={!isUser ? classes.markdownContent : undefined}
                  style={{
                    fontSize: "var(--mantine-font-size-lg)",
                    lineHeight: 1.6,
                    wordBreak: "break-word",
                  }}
                >
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={markdownComponents}
                  >
                    {markdownText}
                  </ReactMarkdown>
                </Box>
                {!isUser && (
                  <SourcesPanel
                    citations={citations}
                    enrichedSources={effectiveSources}
                  />
                )}
              </>
            );
          })()}

          {!isUser && (
            <Box mt="md">
              {/* Action Icons: Download, Copy, Refresh */}
              <Group gap="sm" mb="md">
                {/* <ActionIcon variant="subtle" color="gray" size="sm">
                    <TbDownload size={16} />
                  </ActionIcon> */}
                <Tooltip
                  label={clipboard.copied ? "Copied!" : "Copy to clipboard"}
                >
                  <ActionIcon
                    variant="subtle"
                    color={clipboard.copied ? "green" : "gray"}
                    size="sm"
                    onClick={() => clipboard.copy(getCopyableText())}
                  >
                    {clipboard.copied ? (
                      <TbCheck size={16} />
                    ) : (
                      <TbCopy size={16} />
                    )}
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Regenerate response">
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="sm"
                    onClick={onRefresh}
                    disabled={!onRefresh}
                  >
                    <TbRefresh size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label={playing ? "Stop reading" : "Read message"}>
                  <ActionIcon
                    variant="subtle"
                    color={playing ? "red" : "gray"}
                    size="sm"
                    onClick={handleSpeak}
                  >
                    {playing ? (
                      <TbPlayerStopFilled size={16} />
                    ) : (
                      <TbVolume size={16} />
                    )}
                  </ActionIcon>
                </Tooltip>
              </Group>

              {/* Related Section */}
              {content.extras?.related && content.extras.related.length > 0 && (
                <Box>
                  <Text fw={600} size="md" mb="xs" c="var(--app-text-primary)">
                    Related
                  </Text>
                  <Stack>
                    {content.extras.related.map((link: string, i: number) => (
                      <Group key={i} gap="xs" style={{ cursor: "pointer" }}>
                        <TbCornerDownRight
                          size={14}
                          color="var(--app-accent-primary)"
                        />
                        <Text
                          size="md"
                          c="var(--app-accent-primary)"
                          style={{
                            "&:hover": { textDecoration: "underline" },
                          }}
                        >
                          {link}
                        </Text>
                      </Group>
                    ))}
                  </Stack>
                </Box>
              )}
            </Box>
          )}
        </Box>
      </Box>
    </Paper>
  );
}
