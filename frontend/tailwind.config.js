/** @type {import('tailwindcss').Config}
 *
 * "Obsidian" design system — the app's second-generation identity.
 *
 * Structure: no sidebar; a glass command bar with workspace switching, a
 * sub-tab rail per workspace, and a ⌘K palette. Identity: violet-black
 * surfaces, an electric violet→cyan accent, Sora for display, Manrope for
 * body, JetBrains Mono for figures.
 *
 * Semantic anchors (unchanged contract, new values):
 *   - `slate` is the neutral scale, dark-inverted and hue-shifted violet:
 *     900..700 light ink, 600..400 muted ink, 300..50 fills near the surface.
 *   - `panel` is the card surface; the page sits on `abyss`.
 *   - `brand` is the accent: 600 fill, 700 the BRIGHTER hover, 300/400 glow.
 *   - Chart series colors live in pages/dashboard/charts.tsx (validated data
 *     palette) and deliberately do NOT follow the UI accent.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    borderColor: ({ theme }) => ({
      ...theme('colors'),
      DEFAULT: 'rgba(167, 155, 255, 0.13)',
    }),
    extend: {
      fontFamily: {
        sans: ['"Manrope Variable"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Sora Variable"', '"Manrope Variable"', 'ui-sans-serif', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        abyss: '#08070e',
        panel: { DEFAULT: '#100e1c', raised: '#161327', deep: '#0b0a15' },
        edge: {
          DEFAULT: 'rgba(167,155,255,0.13)',
          soft: 'rgba(167,155,255,0.07)',
          strong: 'rgba(167,155,255,0.25)',
        },
        slate: {
          950: '#f5f3fd', 900: '#efedfa', 800: '#dfdcf0', 700: '#c6c2dd',
          600: '#9b96b8', 500: '#807b9d', 400: '#5f5a7d', 300: '#403c58',
          200: '#2a2740', 100: '#1c1930', 50: '#161327',
        },
        brand: {
          DEFAULT: '#8b5cf6', 50: '#17122b', 100: '#1d1636', 200: '#2a1f52',
          300: '#c4b5fd', 400: '#a78bfa', 500: '#8b5cf6', 600: '#7c3aed',
          700: '#9d71f9', 800: '#5b21b6', 900: '#4c1d95',
        },
        ink: {
          DEFAULT: '#0b0a15', 950: '#08070e', 900: '#0b0a15', 800: '#110f1e',
          700: '#171429', 600: '#201c36',
        },
        midnight: {
          DEFAULT: '#0b0a15', 950: '#08070e', 900: '#0b0a15', 800: '#110f1e',
          700: '#171429', 600: '#201c36',
        },
        silver: {
          DEFAULT: '#aca7c6', 100: '#efedfa', 200: '#dfdcf0', 300: '#c6c2dd',
          400: '#9b96b8', 500: '#807b9d',
        },
        surface: { DEFAULT: '#08070e', card: '#100e1c', sunken: '#0b0a15' },
        good: '#34d399',
        critical: '#f87171',
      },
      boxShadow: {
        card: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 1px 2px rgba(0,0,0,.5), 0 8px 24px -8px rgba(0,0,0,.65)',
        pop: '0 1px 0 0 rgba(255,255,255,0.05) inset, 0 12px 32px rgba(0,0,0,.6), 0 32px 80px -16px rgba(0,0,0,.65)',
        'glow-brand': '0 0 0 1px rgba(139,92,246,.4), 0 0 24px -6px rgba(139,92,246,.5)',
        glass: '0 8px 40px rgba(0,0,0,.55)',
        glow: '0 0 0 1px rgba(255,255,255,.06), 0 14px 50px rgba(0,0,0,.65)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(5px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(.97) translateY(-4px)' },
          '100%': { opacity: '1', transform: 'scale(1) translateY(0)' },
        },
        spectrum: {
          '0%': { backgroundPosition: '0% 50%' },
          '100%': { backgroundPosition: '300% 50%' },
        },
        aurora: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(40px, -30px) scale(1.08)' },
          '66%': { transform: 'translate(-30px, 25px) scale(0.95)' },
        },
      },
      animation: {
        'fade-up': 'fade-up .22s cubic-bezier(.21,1.02,.73,1) both',
        shimmer: 'shimmer 1.8s linear infinite',
        'scale-in': 'scale-in .16s cubic-bezier(.21,1.02,.73,1) both',
        aurora: 'aurora 36s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
