/**
 * Read a pasted payment breakdown such as
 *
 *   BAC C$ 18000 - 19030
 *   BAC $ 10
 *   LAFISE C$ 7000
 *   Banpro dolares 190, 235, 280, 1095
 *
 * into deposits per bank and currency. A line without a bank or a currency
 * keeps the previous line's, so a list of bare amounts under one heading works.
 * A line that says "total" sets that bank's total instead of adding deposits.
 */
import type { Currency } from "./types";

export interface BreakdownBank { id: number; code: string }

export interface BreakdownEntry {
  bankId: number;
  bankCode: string;
  currency: Currency;
  amounts: string[];
  total: string | null;
}

export interface Breakdown { entries: BreakdownEntry[]; skipped: string[] }

const ALIASES: Record<string, string[]> = {
  BAC: ["bac", "credomatic"],
  BANPRO: ["banpro", "produccion"],
  LAFISE: ["lafise", "bancentro"],
  FICHOSA: ["ficohsa", "fichosa"],
};

function normalise(text: string): string {
  return text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/** "18,000.50" / "18.000,50" / "18000" → "18000.50"; "" when it is not an amount. */
export function toAmount(raw: string): string {
  let t = raw.replace(/[^\d.,]/g, "");
  if (!t) return "";
  const comma = t.lastIndexOf(",");
  const dot = t.lastIndexOf(".");
  if (comma >= 0 && dot >= 0) {
    t = comma > dot ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, "");
  } else if (comma >= 0) {
    const tail = t.length - comma - 1;
    t = tail === 3 ? t.replace(/,/g, "") : t.replace(",", ".");
  } else if (dot >= 0 && (t.match(/\./g) ?? []).length > 1) {
    t = t.replace(/\./g, "");
  } else if (dot >= 0 && t.length - dot - 1 === 3 && t.indexOf(".") === dot) {
    t = t.replace(".", ""); // 18.000 → 18000
  }
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? n.toFixed(2) : "";
}

export function parseBreakdown(text: string, banks: BreakdownBank[]): Breakdown {
  const byCode = new Map(banks.map((b) => [b.code.toUpperCase(), b]));
  const entries = new Map<string, BreakdownEntry>();
  const skipped: string[] = [];
  let bank: BreakdownBank | undefined;
  let currency: Currency | undefined;

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    let n = normalise(line);

    for (const [code, words] of Object.entries(ALIASES)) {
      const hit = words.find((w) => new RegExp(`\\b${w}\\b`).test(n));
      if (hit && byCode.has(code)) {
        bank = byCode.get(code);
        n = n.replace(new RegExp(`\\b${hit}\\b`, "g"), " ");
      }
    }
    for (const b of banks) {
      const w = b.code.toLowerCase();
      if (new RegExp(`\\b${w}\\b`).test(n)) {
        bank = b;
        n = n.replace(new RegExp(`\\b${w}\\b`, "g"), " ");
      }
    }

    if (/c\$|\bcs\b|cordoba|\bnio\b/.test(n)) currency = "NIO";
    else if (/\$|\busd\b|dolar|dollar|\bus\b/.test(n)) currency = "USD";

    const isTotal = /\btotal\b/.test(n);
    // Dates and times are not amounts.
    n = n.replace(/\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b/g, " ").replace(/\b\d{1,2}:\d{2}\b/g, " ");
    const amounts = (n.match(/\d[\d.,]*/g) ?? []).map(toAmount).filter(Boolean);

    if (amounts.length === 0) continue; // a heading such as "BAC cordobas"
    if (!bank) {
      skipped.push(line);
      continue;
    }
    const cur: Currency = currency ?? "NIO";
    const key = `${bank.id}:${cur}`;
    const entry = entries.get(key) ?? { bankId: bank.id, bankCode: bank.code, currency: cur, amounts: [], total: null };
    if (isTotal) entry.total = amounts[amounts.length - 1];
    else entry.amounts.push(...amounts);
    entries.set(key, entry);
  }
  return { entries: [...entries.values()], skipped };
}
