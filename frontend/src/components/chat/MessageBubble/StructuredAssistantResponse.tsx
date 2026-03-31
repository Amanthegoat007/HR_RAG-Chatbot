import { Alert, Box, Text, Title } from "@mantine/core";
import { motion, useReducedMotion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TbAlertCircle, TbSparkles } from "react-icons/tb";

import type {
  AssistantResponseBlock,
  AssistantResponsePayload,
} from "@/types/chat.types";
import { fadeUpItem, motionTokens, staggerChildren } from "@/theme/motion";

import classes from "./MessageBubble.module.css";

const markdownComponents = {
  table: ({ node, ...props }: any) => (
    <table className={classes.table} {...props} />
  ),
  th: ({ node, ...props }: any) => <th className={classes.th} {...props} />,
  td: ({ node, ...props }: any) => <td className={classes.td} {...props} />,
};

function MarkdownContent({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <Box className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </Box>
  );
}

function renderBlock(block: AssistantResponseBlock, index: number) {
  switch (block.type) {
    case "title":
      return (
        <motion.div key={`title-${index}`} variants={fadeUpItem}>
          <Title order={3} className={classes.structuredTitle}>
            {block.content}
          </Title>
        </motion.div>
      );

    case "summary":
      return (
        <motion.div key={`summary-${index}`} variants={fadeUpItem}>
          <Box className={classes.summaryCard}>
            <TbSparkles className={classes.summaryIcon} />
            <MarkdownContent
              content={block.content}
              className={classes.structuredSummary}
            />
          </Box>
        </motion.div>
      );

    case "list":
      return (
        <motion.div key={`list-${index}`} variants={fadeUpItem}>
          <Box className={classes.structuredSection}>
            {block.title && (
              <Text className={classes.sectionLabel}>{block.title}</Text>
            )}
            {block.ordered ? (
              <ol className={classes.structuredListOrdered}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${index}-${itemIndex}`}>
                    <MarkdownContent
                      content={item}
                      className={classes.structuredListContent}
                    />
                  </li>
                ))}
              </ol>
            ) : (
              <ul className={classes.structuredList}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${index}-${itemIndex}`}>
                    <MarkdownContent
                      content={item}
                      className={classes.structuredListContent}
                    />
                  </li>
                ))}
              </ul>
            )}
          </Box>
        </motion.div>
      );

    case "comparison":
      return (
        <motion.div key={`comparison-${index}`} variants={fadeUpItem}>
          <Box className={classes.structuredSection}>
            {block.title && (
              <Text className={classes.sectionLabel}>{block.title}</Text>
            )}
            <div className={classes.comparisonGrid}>
              {block.rows.map((row, rowIndex) => (
                <div key={`${index}-${rowIndex}`} className={classes.comparisonRow}>
                  <Text className={classes.comparisonLabel}>{row.label}</Text>
                  <MarkdownContent
                    content={row.content}
                    className={classes.comparisonContent}
                  />
                </div>
              ))}
            </div>
          </Box>
        </motion.div>
      );

    case "note":
      return (
        <motion.div key={`note-${index}`} variants={fadeUpItem}>
          <Alert
            variant="light"
            color={block.tone === "warning" ? "yellow" : "blue"}
            radius="md"
            icon={<TbAlertCircle size={16} />}
            className={classes.structuredNote}
          >
            {block.content}
          </Alert>
        </motion.div>
      );

    default:
      return null;
  }
}

export default function StructuredAssistantResponse({
  payload,
}: {
  payload: AssistantResponsePayload;
}) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      className={classes.structuredResponse}
      initial={reducedMotion ? false : "hidden"}
      animate={reducedMotion ? undefined : "visible"}
      variants={
        reducedMotion
          ? undefined
          : staggerChildren(motionTokens.stagger.tight)
      }
    >
      {payload.blocks.map((block, index) => renderBlock(block, index))}
    </motion.div>
  );
}
