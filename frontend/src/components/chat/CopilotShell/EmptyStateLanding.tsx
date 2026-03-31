import { motion, useReducedMotion } from "framer-motion";

import DashboardHero from "@/components/chat/dashboard/DashboardHero";
import QuickAccessCategories from "@/components/chat/dashboard/QuickAccessCategories";
import {
  subtleFadeUpItem,
  subtleStaggerChildren,
} from "@/theme/motion";

import classes from "./EmptyStateLanding.module.css";

export default function EmptyStateLanding() {
  const reducedMotion = useReducedMotion();

  return (
    <motion.section
      className={classes.landing}
      initial={reducedMotion ? false : "hidden"}
      animate={reducedMotion ? undefined : "visible"}
      variants={reducedMotion ? undefined : subtleStaggerChildren(0.02)}
    >
      <motion.div className={classes.heroFrame} variants={subtleFadeUpItem}>
        <DashboardHero variant="landing" />
      </motion.div>

      <motion.div className={classes.starterRail} variants={subtleFadeUpItem}>
        <QuickAccessCategories variant="landing" />
      </motion.div>
    </motion.section>
  );
}
