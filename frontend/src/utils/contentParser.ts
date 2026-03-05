import type {
  ChartData,
  TableData,
  DataViewData,
  ContentBlock,
  ParsedContent,
} from "./contentParser.types";

export type { ChartData, TableData, DataViewData, ContentBlock, ParsedContent };

/**
 * Parses the raw text content of a message.
 * Supports both legacy format (single type) and new blocks format (mixed content).
 */
export function parseMessageContent(
  text: string,
  isUser: boolean,
): ParsedContent {
  // 1. User messages or empty text are always just text
  if (isUser || !text) {
    return { text: text || "", type: "text", data: null, extras: {} };
  }

  // 2. Try to parse as JSON (Assistant messages should be JSON blocks)
  try {
    const parsed = JSON.parse(text);

    if (parsed && typeof parsed === "object") {
      // Standard format: { type: "blocks", blocks: [...], extras: {...} }
      if (parsed.type === "blocks" && Array.isArray(parsed.blocks)) {
        // Aggregate text from text blocks ONLY for Copy/TTS
        // Titles from charts/tables are now skipped as requested
        const aggregatedText = parsed.blocks
          .map((b: any) => {
            if (b.type === "text" && b.content) return b.content;
            return null;
          })
          .filter(Boolean)
          .join("\n\n");

        return {
          text: aggregatedText,
          type: "blocks",
          data: null,
          blocks: parsed.blocks,
          extras: parsed.extras || {},
        };
      }
    }
  } catch (e) {
    // Not JSON or invalid format
    console.warn("Failed to parse assistant message as JSON blocks:", e);
  }

  // 3. Fallback to plain text (should not happen if backend is updated)
  return { text, type: "text", data: null, extras: {} };
}
