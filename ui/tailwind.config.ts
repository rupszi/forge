import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        mono: ["JetBrains Mono", "Menlo", "monospace"],
      },
      colors: {
        forge: {
          teal: "#14b8a6",      // Ollama/local
          purple: "#a855f7",    // Claude
          coral: "#fb7185",     // Evaluator feedback
          amber: "#f59e0b",     // Warnings
        },
      },
    },
  },
  plugins: [],
};

export default config;
