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
        // Primary — matches the dashboard's validated chart palette (#2a78d6).
        brand: {
          DEFAULT: '#2a78d6', 50: '#f0f6fd', 100: '#dcebfa', 200: '#bcd8f5',
          300: '#8cbcee', 400: '#5599e3', 500: '#2a78d6', 600: '#1d61b8',
          700: '#1b5195', 800: '#1b467b', 900: '#1c3c66',
        },
        // Sidebar / dark surfaces.
        ink: {
          DEFAULT: '#0f141e', 950: '#0a0e16', 900: '#0f141e', 800: '#161d2b',
          700: '#1f2838', 600: '#2a3549',
        },
        // Page surface + hairlines.
        surface: { DEFAULT: '#f3f4f6', card: '#ffffff', sunken: '#eceef1' },
        // Kept for stragglers; harmonized to the new neutrals.
        midnight: {
          DEFAULT: '#0f141e', 950: '#0a0e16', 900: '#0f141e', 800: '#161d2b',
          700: '#1f2838', 600: '#2a3549',
        },
        silver: {
          DEFAULT: '#c7ccd6', 100: '#f5f7fa', 200: '#e6e9ef', 300: '#cdd3de',
          400: '#aab2c2', 500: '#8b94a7',
        },
        // Status — reserved (never used as chart series colors).
        good: '#0ca30c',
        critical: '#d03b3b',
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,20,30,.04), 0 4px 16px rgba(15,20,30,.05)',
        pop: '0 4px 12px rgba(15,20,30,.10), 0 12px 40px rgba(15,20,30,.12)',
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
