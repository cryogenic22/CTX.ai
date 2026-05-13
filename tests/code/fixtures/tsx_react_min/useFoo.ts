/**
 * Custom hook + plain utility — pins hook detection (CP-013).
 */

import { useEffect, useState } from "react";

export function useFoo(): string {
  const [value, setValue] = useState("foo");
  useEffect(() => {
    setValue("foo:" + Date.now());
  }, []);
  return value;
}

export function notAHook(): number {
  return 1;
}
