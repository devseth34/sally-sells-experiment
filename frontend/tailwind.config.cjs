/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(0 0% 4%)",
        foreground: "hsl(0 0% 95%)",
        card: "hsl(0 0% 6%)",
        border: "hsl(0 0% 18%)",
        primary: "hsl(199 89% 48%)",
        muted: "hsl(0 0% 15%)",
        "muted-foreground": "hsl(0 0% 60%)",
        "phase-situation": "hsl(199 89% 48%)",
        "phase-problem": "hsl(45 93% 47%)",
        "phase-consequence": "hsl(0 72% 51%)", 
        "phase-solution": "hsl(142 71% 45%)",
        "phase-ownership": "hsl(280 67% 52%)",
        "phase-terminated": "hsl(0 0% 50%)",
      },
    },
  },
  plugins: [],
}