import type { Config } from "tailwindcss";

/**
 * Every colour is a CSS variable holding space-separated RGB channels, so the
 * whole interface re-themes by swapping variables on <html> — no component
 * needs to know which theme is active, and `bg-ink-50/60` style opacity
 * modifiers keep working.
 *
 * The scales invert between themes: in light, 50 is the palest and 900 the
 * darkest; in dark, 50 is the deepest surface and 900 the brightest text. That
 * is what lets classes written for the light theme read correctly in the dark
 * one without being touched.
 */
const channel = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const scale = (prefix: string, steps: number[]) =>
  Object.fromEntries(steps.map((step) => [step, channel(`${prefix}-${step}`)]));

const STATUS_STEPS = [50, 100, 200, 300, 500, 600, 700, 800, 900];

export default {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        surface: channel("surface"),
        "surface-2": channel("surface-2"),
        ink: scale("ink", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]),
        brand: scale("brand", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]),
        emerald: scale("emerald", STATUS_STEPS),
        amber: scale("amber", STATUS_STEPS),
        red: scale("red", STATUS_STEPS),
        violet: scale("violet", STATUS_STEPS),
        sky: scale("sky", STATUS_STEPS),
        orange: scale("orange", STATUS_STEPS),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        sm: "0 1px 2px 0 rgb(var(--shadow) / 0.06)",
        DEFAULT: "0 1px 3px 0 rgb(var(--shadow) / 0.10), 0 1px 2px -1px rgb(var(--shadow) / 0.10)",
        md: "0 4px 6px -1px rgb(var(--shadow) / 0.10), 0 2px 4px -2px rgb(var(--shadow) / 0.10)",
        lg: "0 10px 15px -3px rgb(var(--shadow) / 0.12), 0 4px 6px -4px rgb(var(--shadow) / 0.12)",
        xl: "0 20px 25px -5px rgb(var(--shadow) / 0.14), 0 8px 10px -6px rgb(var(--shadow) / 0.14)",
      },
    },
  },
  plugins: [],
} satisfies Config;
