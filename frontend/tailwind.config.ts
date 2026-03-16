import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: { primary: "#0A0A14", secondary: "#0F0F1E", tertiary: "#161628", surface: "#1C1C35" },
        border: { default: "#2A2A4A", focus: "#6C63FF" },
        text: { primary: "#E8E8F0", secondary: "#8888AA", muted: "#555570" },
        accent: { violet: "#6C63FF", crimson: "#E94560", emerald: "#10B981", amber: "#F59E0B", cyan: "#06B6D4" },
        chart: { up: "#10B981", down: "#E94560" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"], mono: ["JetBrains Mono", "Consolas", "monospace"] },
      animation: {
        "pulse-once": "pulse-once 500ms ease-in-out",
        "slide-in": "slide-in 300ms ease-out",
      },
      keyframes: {
        "pulse-once": { "0%,100%": { transform: "scale(1)" }, "50%": { transform: "scale(1.02)" } },
        "slide-in": { "0%": { opacity: "0", transform: "translateY(-10px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};
export default config;
