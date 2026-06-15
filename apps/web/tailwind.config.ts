import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        brand: {
          DEFAULT: "var(--brand)",
          hover: "var(--brand-hover)",
          soft: "var(--brand-soft)",
          ink: "var(--brand-ink)",
          fg: "var(--brand-fg)",
        },
        pos: { DEFAULT: "var(--pos)", soft: "var(--pos-soft)", ink: "var(--pos-ink)" },
        ai:  { DEFAULT: "var(--ai)",  soft: "var(--ai-soft)",  ink: "var(--ai-ink)"  },
        neg: { DEFAULT: "var(--neg)", soft: "var(--neg-soft)", ink: "var(--neg-ink)" },
        seg: { DEFAULT: "var(--seg)", soft: "var(--seg-soft)", ink: "var(--seg-ink)" },
        slatey: { DEFAULT: "var(--slatey)", soft: "var(--slatey-soft)", ink: "var(--slatey-ink)" },
      },
      fontFamily: {
        sans:  ["var(--font-plex-sans)",  "system-ui",    "sans-serif"],
        serif: ["var(--font-plex-serif)", "Georgia",      "serif"],
        mono:  ["var(--font-plex-mono)",  "ui-monospace", "monospace"],
      },
      maxWidth: {
        content: "1240px",
        reading: "1000px",
      },
      boxShadow: {
        card:   "0 1px 2px rgba(16,27,43,0.04), 0 1px 3px rgba(16,27,43,0.06)",
        raised: "0 4px 16px rgba(16,27,43,0.10), 0 1px 3px rgba(16,27,43,0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
