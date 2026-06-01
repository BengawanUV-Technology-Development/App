/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    // ONLY scan the directories where the prototype components will live
    "./src/views/**/*.{js,ts,jsx,tsx}",
    "./src/components/ui/**/*.{js,ts,jsx,tsx}",
    "./src/lib/**/*.{js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}