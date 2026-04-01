import { useEffect, useState } from "react";

function getDelayUntilNextMinute(now: Date): number {
  const next = new Date(now);
  next.setSeconds(0, 0);
  next.setMinutes(now.getMinutes() + 1);
  return Math.max(1000, next.getTime() - now.getTime() + 150);
}

export function useGreetingClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const refreshNow = () => setNow(new Date());
    const timeoutId = window.setTimeout(refreshNow, getDelayUntilNextMinute(now));

    window.addEventListener("focus", refreshNow);
    document.addEventListener("visibilitychange", refreshNow);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("focus", refreshNow);
      document.removeEventListener("visibilitychange", refreshNow);
    };
  }, [now]);

  return now;
}
