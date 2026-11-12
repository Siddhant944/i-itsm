import { useEffect, useState } from "react";

import { serverNow } from "./serverTime";

/** The application clock, re-read every `intervalMs` so countdowns tick. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(serverNow);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(serverNow());
    }, intervalMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}
