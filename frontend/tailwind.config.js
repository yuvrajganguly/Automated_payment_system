/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#1F4E79', 600: '#1F4E79', 700: '#1A3F61' },
      },
    },
  },
  plugins: [],
}
