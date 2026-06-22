/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'Inter', 'ui-sans-serif', 'sans-serif'],
      },
      colors: {
        brand: {
          DEFAULT: '#1F4E79', 50: '#eef3f8', 100: '#d6e2ee', 200: '#aec6dd',
          300: '#7ea3c6', 400: '#4d7ba8', 500: '#2b5e8c', 600: '#1F4E79',
          700: '#193f61', 800: '#15314b', 900: '#0f2438',
        },
        midnight: {
          DEFAULT: '#0b1020', 950: '#070a14', 900: '#0b1020', 800: '#111831',
          700: '#18203c', 600: '#222c4d',
        },
        silver: {
          DEFAULT: '#c7ccd6', 100: '#f5f7fa', 200: '#e6e9ef', 300: '#cdd3de',
          400: '#aab2c2', 500: '#8b94a7',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(2,6,23,.04), 0 8px 30px rgba(2,6,23,.08)',
        glass: '0 8px 40px rgba(2,6,23,.18)',
        glow: '0 0 0 1px rgba(255,255,255,.06), 0 14px 50px rgba(2,6,23,.55)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: { 'fade-up': 'fade-up .45s cubic-bezier(.21,1.02,.73,1) both' },
    },
  },
  plugins: [],
}
