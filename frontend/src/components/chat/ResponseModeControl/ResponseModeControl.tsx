import { motion } from "framer-motion";
import { ActionIcon, Tooltip } from "@mantine/core";
import { TbInfoCircle } from "react-icons/tb";

import type { ReasoningMode } from "@/types/chat.types";
import { motionTokens } from "@/theme/motion";

import classes from "./ResponseModeControl.module.css";

export interface ResponseModeControlProps {
  value: ReasoningMode;
  onChange: (value: ReasoningMode) => void;
  disabled?: boolean;
}

const helperText =
  "Deep Think is best for policy comparisons and edge cases. It resets after this message.";

export default function ResponseModeControl({
  value,
  onChange,
  disabled = false,
}: ResponseModeControlProps) {
  const indicatorX = value === "fast" ? "0%" : "100%";

  return (
    <div className={classes.root}>
      <div className={classes.switch}>
        <motion.span
          className={classes.indicator}
          animate={{ x: indicatorX }}
          transition={{
            duration: motionTokens.duration.base,
            ease: motionTokens.ease.standard,
            delay: 0.06,
          }}
        />
        <button
          type="button"
          className={`${classes.option} ${
            value === "fast" ? classes.optionActive : ""
          }`}
          onClick={() => onChange("fast")}
          disabled={disabled}
          aria-pressed={value === "fast"}
        >
          <span className={classes.optionContent}>Fast</span>
        </button>
        <button
          type="button"
          className={`${classes.option} ${
            value === "deep" ? classes.optionActive : ""
          }`}
          onClick={() => onChange("deep")}
          disabled={disabled}
          aria-pressed={value === "deep"}
        >
          <span className={classes.optionContent}>
            <span className={classes.optionIcon} aria-hidden="true">
              ⚡
            </span>
            <span>Deep</span>
          </span>
        </button>
      </div>

      <Tooltip
        label={helperText}
        withArrow
        multiline
        w={280}
        color="dark"
        openDelay={120}
        position="top-end"
      >
        <ActionIcon
          variant="subtle"
          radius="xl"
          size="sm"
          className={classes.infoButton}
          disabled={disabled}
          aria-label="Explain response modes"
        >
          <TbInfoCircle size={14} />
        </ActionIcon>
      </Tooltip>
    </div>
  );
}
