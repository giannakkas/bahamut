import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./providers/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bah: {
          bg: "#0a0e17",
          surface: "#0d1220",
          border: "rgba(6,182,212,0.12)",
          "border-strong": "rgba(6,182,212,0.25)",
          muted: "#4a5568",
          subtle: "#64748b",
          text: "#c8d6e5",
          heading: "#e2e8f0",
          cyan: "#06b6d4",
          purple: "#8b5cf6",
          green: "#10b981",
          red: "#ef4444",
          amber: "#f59e0b",
          teal: "#14b8a6",
          blue: "#3b82f6",
          pink: "#ec4899",
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "SF Mono",
          "Cascadia Code",
          "monospace",
        ],
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease forwards",
        "slide-up": "slideUp 0.3s ease forwards",
        pulse: "pulse 1.5s infinite",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0", transform: "translateY(-8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
