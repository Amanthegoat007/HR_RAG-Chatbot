import { Text } from "@mantine/core";
import { motion, useReducedMotion } from "framer-motion";
import {
  TbHeartbeat,
  TbPlane,
  TbBriefcase2,
  TbBeach,
} from "react-icons/tb";
import { IconType } from "react-icons";
import { QuickActionCard } from "@/components/ui";
import { subtleFadeUpItem, subtleStaggerChildren } from "@/theme/motion";

import classes from "./QuickAccessCategories.module.css";

export interface QuickAccessCategoriesProps {
  variant?: "default" | "landing";
}

export default function QuickAccessCategories({
  variant = "default",
}: QuickAccessCategoriesProps) {
  const isLanding = variant === "landing";
  const reducedMotion = useReducedMotion();
  const QUICK_ACTIONS: {
    title: string;
    description: string;
    icon: IconType;
    prompt: string;
  }[] = [
    {
      title: "Medical Benefits",
      description: "Coverage, dependents, and eligibility rules",
      icon: TbHeartbeat,
      prompt:
        "Can you explain the medical benefits eligibility and dependent coverage policy?",
    },
    {
      title: "Air Tickets",
      description: "Allowances, claim rules, and family coverage",
      icon: TbPlane,
      prompt:
        "Can both spouses claim individual air ticket allowances if they both work at Esyasoft?",
    },
    {
      title: "End of Service",
      description: "Calculation rules and nationality differences",
      icon: TbBriefcase2,
      prompt:
        "How is end-of-service calculated for UAE nationals compared with expatriates?",
    },
    {
      title: "Leave Policy",
      description: "Annual leave, sick leave, and entitlement questions",
      icon: TbBeach,
      prompt:
        "What are the main leave entitlements and conditions I should know about?",
    },
  ];

  return (
    <motion.section
      className={classes.root}
      initial={reducedMotion ? false : "hidden"}
      animate={reducedMotion ? undefined : "visible"}
      variants={reducedMotion ? undefined : subtleStaggerChildren(0.04)}
      data-variant={variant}
    >
      <div
        className={`${classes.header} ${
          isLanding ? classes.headerLanding : ""
        }`}
      >
        {isLanding ? (
          <>
            <Text className={classes.landingTitle}>Start here!</Text>
          </>
        ) : (
          <>
            <Text className={classes.eyebrow}>Start here!</Text>
            <Text fw={700} size="xl" className={classes.title}>
              Pick a topic and we’ll drop it into the composer
            </Text>
          </>
        )}
      </div>

      <motion.div className={classes.grid}>
        {QUICK_ACTIONS.map((action) => (
          <motion.div
            key={action.title}
            className={classes.cardCell}
            variants={subtleFadeUpItem}
          >
            <QuickActionCard
              title={action.title}
              description={action.description}
              icon={action.icon}
              variant={variant}
              onClick={() => {
                window.dispatchEvent(
                  new CustomEvent("copilot:starter-prompt", {
                    detail: { prompt: action.prompt },
                  }),
                );
              }}
            />
          </motion.div>
        ))}
      </motion.div>
    </motion.section>
  );
}
