/**
 * Plain utility module — exported functions + type. Pins the
 * exported-utility detection path (CP-012).
 */

export type LabelStyle = "compact" | "verbose";

export function formatLabel(raw: string, style: LabelStyle = "compact"): string {
  if (style === "compact") return raw.slice(0, 32);
  return raw;
}

export const SEPARATOR = " | ";

function privateHelper(s: string): string {
  return s.trim();
}
