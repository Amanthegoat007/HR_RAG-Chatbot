export interface GreetingCopy {
  eyebrow: string;
  headline: string;
  prompt: string;
  subtitle: string;
}

type TimeBucket = "morning" | "afternoon" | "evening";

const PROMPTS: Record<TimeBucket, string[]> = {
  morning: [
    "What should we sort out first?",
    "Ready to start the day with policy clarity?",
    "Which people question needs a clean answer this morning?",
  ],
  afternoon: [
    "What needs a clean answer right now?",
    "Which policy question should we pick up next?",
    "Need a quick read on an HR decision?",
  ],
  evening: [
    "What should we settle before sign-off?",
    "Need one more clean answer before the day wraps?",
    "Which open people question should we close out?",
  ],
};

const SALUTATIONS: Record<TimeBucket, string> = {
  morning: "Good morning",
  afternoon: "Good afternoon",
  evening: "Good evening",
};

function getTimeBucket(date: Date): TimeBucket {
  const hour = date.getHours();
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}

function getSeed(date: Date, displayName: string, roleLabel: string): number {
  const daySeed =
    date.getFullYear() * 372 + (date.getMonth() + 1) * 31 + date.getDate();
  return daySeed + roleLabel.length + displayName.length;
}

export function buildGreetingCopy(
  identity: {
    displayName: string;
    roleLabel: string;
  },
  date = new Date(),
): GreetingCopy {
  const bucket = getTimeBucket(date);
  const prompts = PROMPTS[bucket];
  const prompt =
    prompts[
      getSeed(date, identity.displayName, identity.roleLabel) % prompts.length
    ];

  return {
    eyebrow: identity.roleLabel,
    headline: `${SALUTATIONS[bucket]}, ${identity.displayName}.`,
    prompt,
    subtitle:
      identity.roleLabel === "HR Administrator"
        ? "Policies, benefits, leave, session attachments, and library intake all live in one workspace."
        : "Policies, benefits, leave, payroll, and session attachments are all within reach here.",
  };
}
