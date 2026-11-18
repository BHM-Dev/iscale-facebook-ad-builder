import containerQueries from '@tailwindcss/container-queries';

function neutralAccent() {
  return {
    // Light tints sit a step darker than gray-50/100/200 so selected cards and rows still stand out.
    50: '#ededed', 100: '#e2e2e2', 200: '#cccccc', 300: '#b3b3b3', 400: '#8a8a8a',
    500: '#404040', 600: '#171717', 700: '#000000', 800: '#000000', 900: '#000000', 950: '#000000',
  };
}

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Restyle (Steve, 2026-11-18; Joel: "font is hard to read, very AI"). Neutral near-black accent like
      // AdStellar/Linear instead of indigo/violet/purple, darker secondary text, semibold instead of bold.
      // Remapped here so every page changes at once; amber/orange are left alone because they also mean "warning".
      colors: {
        indigo: neutralAccent(),
        violet: neutralAccent(),
        purple: neutralAccent(),
      },
      textColor: {
        gray: { 400: '#6b7280', 500: '#4b5563', 600: '#374151' },
      },
      fontWeight: {
        bold: '600',
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', '-apple-system', '"Segoe UI"', 'Helvetica', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [
    containerQueries,
  ],
}
