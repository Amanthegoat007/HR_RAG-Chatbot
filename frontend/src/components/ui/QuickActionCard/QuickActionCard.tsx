import {
  Box,
  Paper,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { TbArrowUpRight, TbLayoutDashboard } from "react-icons/tb";

import { QuickActionCardProps } from "./QuickActionCard.types";
import classes from "./QuickActionCard.module.css";

export default function QuickActionCard({
  title,
  description,
  icon: Icon,
  onClick,
  variant = "default",
}: QuickActionCardProps) {
  const ActualIcon = Icon || TbLayoutDashboard;

  return (
    <UnstyledButton
      onClick={onClick}
      className={classes.cardButton}
      data-variant={variant}
    >
      <Paper
        radius="xl"
        className={`${classes.cardSurface} ${
          variant === "landing" ? classes.cardSurfaceLanding : ""
        }`}
      >
        <div className={classes.header}>
          <Box className={classes.iconBadge}>
            <ActualIcon size={20} />
          </Box>
          <Box className={classes.arrowBadge}>
            <TbArrowUpRight size={14} />
          </Box>
        </div>

        <div className={classes.content}>
          <Text lineClamp={2} className={classes.title}>
            {title}
          </Text>
          <Text lineClamp={3} className={classes.description}>
            {description}
          </Text>
        </div>
      </Paper>
    </UnstyledButton>
  );
}
