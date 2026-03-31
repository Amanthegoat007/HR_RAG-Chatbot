import type { Transition, Variants } from "framer-motion";

export const motionTokens = {
  duration: {
    instant: 0.12,
    base: 0.22,
    slow: 0.42,
    hero: 0.7,
  },
  ease: {
    standard: [0.22, 1, 0.36, 1] as const,
    smooth: [0.33, 1, 0.68, 1] as const,
  },
  stagger: {
    tight: 0.05,
    relaxed: 0.08,
  },
};

export const fadeUpItem: Variants = {
  hidden: {
    opacity: 0,
    y: 14,
    filter: "blur(10px)",
  },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: {
      duration: motionTokens.duration.slow,
      ease: motionTokens.ease.standard,
    },
  },
};

export const subtleFadeUpItem: Variants = {
  hidden: {
    opacity: 0,
    y: 8,
    filter: "blur(6px)",
  },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: {
      duration: motionTokens.duration.base,
      ease: motionTokens.ease.standard,
    },
  },
};

export const staggerChildren = (delayChildren = 0): Variants => ({
  hidden: {},
  visible: {
    transition: {
      delayChildren,
      staggerChildren: motionTokens.stagger.relaxed,
    },
  },
});

export const subtleStaggerChildren = (delayChildren = 0): Variants => ({
  hidden: {},
  visible: {
    transition: {
      delayChildren,
      staggerChildren: motionTokens.stagger.tight,
    },
  },
});

export const expandTransition: Transition = {
  duration: motionTokens.duration.base,
  ease: motionTokens.ease.standard,
};
