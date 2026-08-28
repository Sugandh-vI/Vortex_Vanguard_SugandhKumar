/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070C16",
          900: "#0B1220",
          850: "#0E1627",
          800: "#111B30",
          700: "#16233C",
          600: "#1E2E4E",
        },
        line: "#1D2A45",
        mist: {
          DEFAULT: "#8FA3C0",
          dim: "#5D6F8F",
          bright: "#C7D4EA",
        },
        accent: {
          DEFAULT: "#4F8EF7",
          soft: "#274060",
        },
        conf: {
          high: "#34D399",
          medium: "#F5B04C",
          low: "#F97066",
          abstain: "#A78BFA",
        },
        blocked: "#F87171",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
