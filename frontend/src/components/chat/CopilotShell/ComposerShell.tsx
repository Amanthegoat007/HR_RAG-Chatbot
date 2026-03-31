import { motion } from "framer-motion";

import ChatInput from "@/components/chat/ChatInput";
import { motionTokens } from "@/theme/motion";

import classes from "./ComposerShell.module.css";

export interface ComposerShellProps {
  isEmpty: boolean;
}

export default function ComposerShell({ isEmpty }: ComposerShellProps) {
  return (
    <motion.div
      layout
      className={`${classes.dock} ${isEmpty ? classes.dockEmpty : ""}`}
      transition={{
        duration: motionTokens.duration.base,
        ease: motionTokens.ease.standard,
      }}
    >
      <div className={classes.inner}>
        <ChatInput isHeroMode={isEmpty} />
      </div>
    </motion.div>
  );
}
