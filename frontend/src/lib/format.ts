import type { Currency } from "./types";

const SYMBOLS: Record<string, string> = { USD: "$", NIO: "C$" };

/** Money is formatted, never converted. A USD figure and a cordoba figure are
 *  shown side by side and never summed. */
export function money(value: string | number | null | undefined, currency?: Currency | string) {
  const amount = Number(value ?? 0);
  const formatted = amount.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const symbol = currency ? SYMBOLS[currency] ?? "" : "";
  return `${symbol}${formatted}`;
}

export function compactMoney(value: string | number | null | undefined, currency?: string) {
  const amount = Number(value ?? 0);
  const symbol = currency ? SYMBOLS[currency] ?? "" : "";
  if (Math.abs(amount) >= 1_000_000) return `${symbol}${(amount / 1_000_000).toFixed(1)}M`;
  if (Math.abs(amount) >= 10_000) return `${symbol}${(amount / 1000).toFixed(1)}k`;
  return `${symbol}${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function shortDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value.length <= 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function dateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function monthStart(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
}

export function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export function bytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function titleCase(value: string) {
  return value
    .toLowerCase()
    .split(/[\s_]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
