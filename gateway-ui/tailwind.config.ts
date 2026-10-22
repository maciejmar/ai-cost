import type { Config } from "tailwindcss";

// Kolory jako tokeny CSS (globals.css) — jasny i ciemny motyw w jednym miejscu
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: token("background"),
        surface: token("surface"),
        foreground: token("foreground"),
        muted: token("muted"),
        "muted-foreground": token("muted-foreground"),
        border: token("border"),
        primary: token("primary"),
        "primary-foreground": token("primary-foreground"),
        destructive: token("destructive"),
        good: token("good"),
        warning: token("warning"),
      },
      borderRadius: { lg: "10px", md: "8px", sm: "6px" },
      fontFamily: { sans: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
    },
  },
  plugins: [],
} satisfies Config;
