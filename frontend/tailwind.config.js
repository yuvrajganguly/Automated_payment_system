/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#1F4E79',
          50:  '#eef3f8',
          100: '#d6e2ee',
          200: '#aec6dd',
          300: '#7ea3c6',
          400: '#4d7ba8',
          500: '#2b5e8c',
          600: '#1F4E79',
          700: '#193f61',
          800: '#15314b',
          900: '#0f2438',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,29,51,.04), 0 4px 16px rgba(16,29,51,.06)',
      },
    },
  },
  plugins: [],
}
