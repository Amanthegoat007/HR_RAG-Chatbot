import { Loader, Stack, Text } from "@mantine/core";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { RefObject } from "react";

import ChatWindow from "@/components/chat/ChatWindow";
import { motionTokens } from "@/theme/motion";

import EmptyStateLanding from "./EmptyStateLanding";
import classes from "./TranscriptViewport.module.css";

export interface TranscriptViewportProps {
  isEmpty: boolean;
  isLoadingConversation?: boolean;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
}

export default function TranscriptViewport({
  isEmpty,
  isLoadingConversation = false,
  scrollContainerRef,
}: TranscriptViewportProps) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      ref={scrollContainerRef}
      layoutScroll
      className={classes.viewport}
      transition={{
        duration: motionTokens.duration.base,
        ease: motionTokens.ease.smooth,
      }}
    >
      <AnimatePresence initial={false} mode="wait">
        {isLoadingConversation ? (
          <motion.div
            key="conversation-loading"
            className={classes.loadingState}
            initial={reducedMotion ? false : { opacity: 0, y: 12 }}
            animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -10 }}
            transition={{
              duration: motionTokens.duration.slow,
              ease: motionTokens.ease.standard,
            }}
          >
            <Stack gap="sm" align="center" className={classes.loadingCard}>
              <Loader size="sm" color="var(--app-accent-primary)" />
              <Text className={classes.loadingTitle}>Opening conversation</Text>
              <Text className={classes.loadingCopy}>
                Pulling the transcript, sources, and previous context into view.
              </Text>
            </Stack>
          </motion.div>
        ) : isEmpty ? (
          <motion.div
            key="empty-state"
            className={classes.emptyState}
            initial={reducedMotion ? false : { opacity: 0, y: 16 }}
            animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -10 }}
            transition={{
              duration: motionTokens.duration.slow,
              ease: motionTokens.ease.standard,
            }}
          >
            <EmptyStateLanding />
          </motion.div>
        ) : (
          <motion.div
            key="conversation"
            className={classes.conversation}
            initial={reducedMotion ? false : { opacity: 0, y: 12 }}
            animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
            transition={{
              duration: motionTokens.duration.slow,
              ease: motionTokens.ease.standard,
            }}
          >
            <ChatWindow scrollContainerRef={scrollContainerRef} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
