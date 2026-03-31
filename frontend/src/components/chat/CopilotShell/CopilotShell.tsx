import { Box, Container } from "@mantine/core";
import { useRef } from "react";

import ComposerShell from "./ComposerShell";
import TranscriptViewport from "./TranscriptViewport";
import classes from "./CopilotShell.module.css";

export default function CopilotShell({ isEmpty }: { isEmpty: boolean }) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  return (
    <Box className={classes.shellRoot}>
      <Container size={1180} className={classes.shellContainer}>
        <div className={classes.shellGrid}>
          <TranscriptViewport
            isEmpty={isEmpty}
            scrollContainerRef={scrollContainerRef}
          />
          <ComposerShell isEmpty={isEmpty} />
        </div>
      </Container>
    </Box>
  );
}
