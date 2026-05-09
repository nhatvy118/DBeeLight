/** @type {import('tailwindcss').Config} */
export default {
  // Class-based dark mode: ThemeContext toggles ``dark`` on <html>; every
  // component opts in via ``dark:`` variants. Avoids the OS-driven
  // ``media`` strategy so the user controls the theme explicitly.
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [require('@tailwindcss/typography')],
}

