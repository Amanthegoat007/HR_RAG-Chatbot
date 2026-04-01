import {
  Paper,
  Text,
  Loader,
  Box,
  Group,
  ActionIcon,
  Stack,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  TbCopy,
  TbRefresh,
  TbCornerDownRight,
  TbFileDescription,
  TbCheck,
} from "react-icons/tb";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { parseMessageContent } from "@/utils/contentParser";
import { ChatTable } from "../ChatTable";
import { ChatChart } from "../ChatChart";
import { ChatDataView } from "../ChatDataView";
import type { ChartData, TableData, DataViewData } from "@/utils/contentParser";
import { TbFileDescription as TbSourceIcon } from "react-icons/tb";
import StructuredAssistantResponse from "./StructuredAssistantResponse";
import { expandTransition, fadeUpItem } from "@/theme/motion";
import type { MessageMetadata } from "@/types/chat.types";

import type { MessageBubbleProps } from "./MessageBubble.types";
import classes from "./MessageBubble.module.css";

// ── Source Citation Extraction ─────────────────────────────────────
interface SourceCitation {
  filename: string;
  detail: string; // page/section info
}

type TrustSummary = NonNullable<MessageMetadata["trustSummary"]>;
type RelatedSuggestion = NonNullable<MessageMetadata["relatedSuggestions"]>[number];

function dispatchPromptFill(prompt: string) {
  const trimmedPrompt = prompt.trim();
  if (!trimmedPrompt) return;

  window.dispatchEvent(
    new CustomEvent("copilot:starter-prompt", {
      detail: { prompt: trimmedPrompt },
    }),
  );
}

function hasRenderableStructuredPayload(payload: any): boolean {
  return Boolean(payload?.blocks?.some((block: any) => block?.type !== "title"));
}

async function writeTextToClipboard(text: string): Promise<boolean> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return false;
  }

  if (navigator?.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall back for non-secure contexts or restricted clipboard permissions.
    }
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.top = "0";
    textarea.style.left = "-9999px";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";

    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}

function normalizeAssistantMarkdown(rawText: string): string {
  let text = rawText
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/([.!?:])\s+(\d+\.\s+)/g, "$1\n\n$2")
    .replace(/([a-z])\s+(\d+\.\s+\*\*)/g, "$1\n\n$2")
    .replace(/([.!?:])\s+([-*]\s+)/g, "$1\n\n$2")
    .replace(/(\d+\.)\s+—\s+/g, "$1 ");

  // Strip "### Answer" / "**Answer**" / "Answer:" headers the LLM may produce
  text = text.replace(/^#{1,4}\s*Answer\s*\n+/i, "");
  text = text.replace(/^\*{1,2}Answer\*{1,2}\s*\n+/i, "");
  text = text.replace(/^Answer[:\s]*\n+/i, "");

  // Strip inline (Source: ...) citations — sources are shown separately
  text = text.replace(/\n?\(Source:[^)]+\)\s*/g, "\n");

  // Strip <END_ANSWER> stop token
  text = text.replace(/<END_ANSWER>/g, "");

  return text.trim();
}

/**
 * Close unclosed markdown markers so ReactMarkdown renders correctly
 * during streaming. Handles code blocks, inline code, bold, and italic.
 *
 * Improved: processes text line-by-line to avoid miscounting list-item
 * asterisks (e.g., `* **Phase 1:**`) as unclosed italic markers.
 */
function closeStreamingMarkdown(text: string): string {
  if (!text) return text;

  // 1. Close unclosed fenced code blocks (```)
  const codeBlockCount = (text.match(/```/g) || []).length;
  if (codeBlockCount % 2 !== 0) {
    text += "\n```";
  }

  // 2. Close unclosed inline code (`) — skip inside fenced code blocks
  //    Only count backticks outside of fenced code block regions
  let outsideCodeBlocks = text;
  if (codeBlockCount >= 2) {
    // Remove fenced code block contents for counting purposes
    outsideCodeBlocks = text.replace(/```[\s\S]*?```/g, "");
  }
  const inlineCodeCount = (outsideCodeBlocks.match(/(?<!`)`(?!`)/g) || []).length;
  if (inlineCodeCount % 2 !== 0) {
    text += "`";
  }

  // 3. Close unclosed bold (**) — count only actual formatting markers
  //    Exclude list-item leading asterisks: lines starting with "* "
  const contentForBold = outsideCodeBlocks
    .split("\n")
    .map(line => {
      const stripped = line.trimStart();
      // Strip leading list marker "* " or "- " to avoid miscounting
      if (stripped.startsWith("* ")) return stripped.slice(2);
      return stripped;
    })
    .join("\n");
  const boldCount = (contentForBold.match(/\*\*(?!\*)/g) || []).length;
  if (boldCount % 2 !== 0) {
    text += "**";
  }

  // 4. Close unclosed italic (*) — check after bold cleanup
  //    Only count lone asterisks that are NOT part of ** and NOT list markers
  const afterBoldClose = boldCount % 2 !== 0 ? contentForBold + "**" : contentForBold;
  const withoutBold = afterBoldClose.replace(/\*\*/g, "");
  const italicCount = (withoutBold.match(/\*/g) || []).length;
  if (italicCount % 2 !== 0) {
    text += "*";
  }

  return text;
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

/** Renders the sources panel — collapsed by default, click to expand */
function SourcesPanel({
  citations,
  enrichedSources,
  trustSummary,
}: {
  citations: SourceCitation[];
  enrichedSources?: any[];
  trustSummary?: TrustSummary;
}) {
  const [showSources, setShowSources] = useState(false);
  // Prefer enriched sources from backend (have chunk text) over citation extraction
  const hasEnriched = enrichedSources && enrichedSources.length > 0;
  const items = hasEnriched ? enrichedSources : citations;
  if (!items || items.length === 0) return null;

  const label = items.length === 1 ? "Source" : `Sources (${items.length})`;

  return (
    <div className={classes.sourcesPanel}>
      <div
        className={classes.sourcesLabel}
        onClick={() => setShowSources(!showSources)}
        style={{ cursor: "pointer", userSelect: "none" }}
      >
        <TbSourceIcon size={12} />
        {label}
        <span style={{ marginLeft: "4px", fontSize: "0.7em" }}>
          {showSources ? "▲" : "▼"}
        </span>
      </div>
      <AnimatePresence initial={false}>
        {showSources && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={expandTransition}
          >
            <div>
              <SourceTrustRow trustSummary={trustSummary} />
              {hasEnriched
                ? enrichedSources!.map((src: any, i: number) => (
                    <ExpandableSourceCard key={i} source={src} />
                  ))
                : citations.map((c, i) => <SourceChip key={i} citation={c} />)}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function TrustToken({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <span className={classes.trustToken} data-tone={tone}>
      {label}
    </span>
  );
}

function SourceTrustRow({ trustSummary }: { trustSummary?: TrustSummary }) {
  if (!trustSummary) return null;

  const trustBits = [
    trustSummary.policyTitle,
    trustSummary.policyVersion,
    trustSummary.effectiveDateLabel
      ? `Effective ${trustSummary.effectiveDateLabel}`
      : undefined,
    trustSummary.owner ? `Owner: ${trustSummary.owner}` : undefined,
    trustSummary.jurisdiction,
    trustSummary.freshnessLabel,
    trustSummary.groundingLabel,
  ].filter(Boolean) as string[];

  if (trustBits.length === 0 && !trustSummary.hasConflict) {
    return null;
  }

  return (
    <div className={classes.trustRow}>
      <Text className={classes.trustLabel}>Trust signals</Text>
      <div className={classes.trustTokens}>
        {trustBits.map((label) => (
          <TrustToken key={label} label={label} />
        ))}
        {trustSummary.hasConflict && trustSummary.conflictLabel ? (
          <TrustToken label={trustSummary.conflictLabel} tone="warning" />
        ) : null}
      </div>
    </div>
  );
}

function TryNextSuggestions({
  suggestions,
}: {
  suggestions: RelatedSuggestion[];
}) {
  if (!suggestions.length) return null;

  return (
    <Box className={classes.suggestionRail}>
      <Text className={classes.suggestionRailLabel}>Try next</Text>
      <div className={classes.suggestionTokens}>
        {suggestions.map((suggestion) => (
          <button
            key={`${suggestion.label}:${suggestion.prompt}`}
            type="button"
            className={classes.suggestionToken}
            onClick={() => dispatchPromptFill(suggestion.prompt)}
          >
            <TbCornerDownRight size={13} />
            <span>{suggestion.label}</span>
          </button>
        ))}
      </div>
    </Box>
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
      <AnimatePresence initial={false}>
        {expanded && text && (
          <motion.div
            className={classes.sourceCardBody}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={expandTransition}
          >
          <Text
            size="sm"
            c="var(--app-text-secondary)"
            style={{ lineHeight: 1.6, whiteSpace: "pre-wrap" }}
          >
            {text}
          </Text>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Pipeline stage indicator — shows during loading/streaming */
function PipelineStageIndicator({ stages }: { stages: any[] }) {
  if (!stages || stages.length === 0) return null;
  const allStages = [
    { id: "embedding", defaultLabel: "Embedding query..." },
    { id: "searching", defaultLabel: "Searching documents..." },
    { id: "reranking", defaultLabel: "Reranking results..." },
    { id: "generating", defaultLabel: "Generating response..." },
  ];

  // Find the currently active stage, or if generating is done, we might not show anything
  const activeStageDef = allStages.find((def) => {
    const s = stages.find((st) => st.stage === def.id);
    return s && s.status === "active";
  });

  if (!activeStageDef) return null;

  const stageData = stages.find((s) => s.stage === activeStageDef.id);
  const label = stageData?.label || activeStageDef.defaultLabel;

  return (
    <Group gap="xs" style={{ color: "var(--app-text-secondary)", fontStyle: "italic" }}>
      <Loader size="xs" color="gray" type="oval" />
      <Text size="sm">{label}</Text>
    </Group>
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
  streaming,
  attachment,
  onRefresh,
  stages,
  sources,
  metadata,
  responsePayload,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const reducedMotion = useReducedMotion();
  const rowClassName = [
    classes.messageRow,
    isUser ? classes.messageRowUser : classes.messageRowAssistant,
  ].join(" ");
  const surfaceClassName = [
    classes.messageSurface,
    isUser ? classes.messageSurfaceUser : classes.messageSurfaceAssistant,
  ].join(" ");

  // Parse structured data if assistant
  const content = useMemo(() => {
    return parseMessageContent(text, isUser);
  }, [text, isUser]);

  const structuredPayload = hasRenderableStructuredPayload(responsePayload)
    ? responsePayload
    : hasRenderableStructuredPayload(metadata?.responsePayload)
      ? metadata?.responsePayload
      : undefined;

  // Merge: prefer SSE sources (live), fall back to DB metadata-backed sources
  const effectiveSources =
    sources && sources.length > 0
      ? sources
      : metadata?.sources || structuredPayload?.sources || [];
  const relatedSuggestions: RelatedSuggestion[] = metadata?.relatedSuggestions
    ? metadata.relatedSuggestions
    : (content.extras?.related || []).map((prompt: string) => ({
        label: prompt,
        prompt,
      }));
  const [copied, setCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);

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

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    const copyableText = getCopyableText();
    if (!copyableText) {
      return;
    }

    const success = await writeTextToClipboard(copyableText);
    if (!success) {
      return;
    }

    setCopied(true);

    if (copyResetTimeoutRef.current !== null) {
      window.clearTimeout(copyResetTimeoutRef.current);
    }

    copyResetTimeoutRef.current = window.setTimeout(() => {
      setCopied(false);
      copyResetTimeoutRef.current = null;
    }, 2000);
  };

  if (loading && !text.trim() && !structuredPayload) {
    return (
      <Box className={classes.loadingRow}>
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
    <motion.div
      layout="position"
      initial={isUser || reducedMotion ? false : "hidden"}
      whileInView={isUser || reducedMotion ? undefined : "visible"}
      viewport={isUser || reducedMotion ? undefined : { once: true, amount: 0.18 }}
      variants={isUser || reducedMotion ? undefined : fadeUpItem}
      className={rowClassName}
    >
      <Paper
        px="md"
        radius="lg"
        withBorder={false}
        className={surfaceClassName}
      >
      {!isUser && (
        <Box className={classes.assistantMarker} />
      )}
      <Box className={classes.messageBody}>
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
            if (!isUser && structuredPayload && structuredPayload.blocks.length > 0) {
              return (
                <>
                  <StructuredAssistantResponse payload={structuredPayload} />
                  <SourcesPanel
                    citations={[]}
                    enrichedSources={effectiveSources}
                    trustSummary={metadata?.trustSummary}
                  />
                </>
              );
            }

            // Handle blocks format (Standard format for assistant)
            if (content.type === "blocks" && content.blocks) {
              return (
                <Stack gap="md">
                  {content.blocks.map((block, index) => {
                    switch (block.type) {
                      case "text": {
                        const normalizedBlockMarkdown = closeStreamingMarkdown(
                          normalizeAssistantMarkdown(block.content || ""));
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
            const textForParsing = content.text;
            const { cleanText: answerText, citations } = !isUser
              ? extractSourceCitations(textForParsing)
              : { cleanText: textForParsing, citations: [] };
              
            // Conditionally normalize only when fully done to prevent rendering glitches mid-stream
            const shouldNormalize = !isUser && !loading && !streaming;
            const processedText = shouldNormalize 
              ? normalizeAssistantMarkdown(answerText) 
              : answerText;
              
            const markdownText = !isUser
              ? closeStreamingMarkdown(processedText)
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
                    trustSummary={metadata?.trustSummary}
                  />
                )}
              </>
            );
          })()}

          {!isUser && (
            <Box mt="md">
              <TryNextSuggestions suggestions={relatedSuggestions} />

              {/* Action Icons */}
              <Group gap="sm" mb="md">
                <Tooltip label={copied ? "Copied!" : "Copy to clipboard"}>
                  <ActionIcon
                    variant="subtle"
                    color={copied ? "green" : "gray"}
                    size="sm"
                    onClick={handleCopy}
                  >
                    {copied ? (
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
              </Group>

            </Box>
          )}
        </Box>
      </Box>
      </Paper>
    </motion.div>
  );
}
