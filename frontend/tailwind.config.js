/** @type {import('tailwindcss').Config}
 *
 * Midnight design system.
 *
 * The whole app is authored against a small set of semantic anchors:
 *   - `slate` is the NEUTRAL SCALE, dark-inverted: 900..700 are light ink
 *     (headings/body), 600..400 secondary/muted ink, 300..50 fills that get
 *     progressively closer to the surface. Every legacy `text-slate-500` /
 *     `bg-slate-100` in the codebase lands on the right dark value through
 *     this one table — the scale's *semantics* (500 = muted) are unchanged.
 *   - `panel` is the card surface; the page sits on `abyss`.
 *   - `brand` is tuned for dark surfaces: 600 is the button fill, 700 the
 *     *brighter* hover (light emits upward on dark), 300/400 are link/glow.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // Hairlines by default: a bare `border` class anywhere renders the
    // system's edge color instead of Tailwind's light gray.
    borderColor: ({ theme }) => ({
      ...theme('colors'),
      DEFAULT: 'rgba(148, 163, 190, 0.14)',
    }),
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'Inter', 'ui-sans-serif', 'sans-serif'],
      },
      colors: {
        // Page + surface layers (deep, never flat #000).
        abyss: '#07090f',
        panel: { DEFAULT: '#0e1220', raised: '#131828', deep: '#0a0d18' },
        edge: {
          DEFAULT: 'rgba(148,163,190,0.14)',
          soft: 'rgba(148,163,190,0.08)',
          strong: 'rgba(148,163,190,0.24)',
        },
        // Neutral scale, dark-inverted (see header comment).
        slate: {
          950: '#f6f8fc', 900: '#eef1f8', 800: '#dde2ee', 700: '#c3cbdc',
          600: '#98a2b8', 500: '#7d879d', 400: '#5d6780', 300: '#3c4459',
          200: '#272e40', 100: '#1a2030', 50: '#151a28',
        },
        // Accent — chart-blue family stepped for dark surfaces.
        brand: {
          DEFAULT: '#3987e5', 50: '#0f1a2e', 100: '#12233f', 200: '#1a2c4d',
          300: '#7ab2f2', 400: '#549ae9', 500: '#3987e5', 600: '#2f77d0',
          700: '#4f97ee', 800: '#1d4f8f', 900: '#173c6b',
        },
        ink: {
          DEFAULT: '#0a0d16', 950: '#070910', 900: '#0a0d16', 800: '#10141f',
          700: '#161b29', 600: '#1f2534',
        },
        midnight: {
          DEFAULT: '#0a0d16', 950: '#070910', 900: '#0a0d16', 800: '#10141f',
          700: '#161b29', 600: '#1f2534',
        },
        silver: {
          DEFAULT: '#aab2c5', 100: '#eef1f8', 200: '#dde2ee', 300: '#c3cbdc',
          400: '#98a2b8', 500: '#7d879d',
        },
        surface: { DEFAULT: '#07090f', card: '#0e1220', sunken: '#0a0d18' },
        good: '#34d399',
        critical: '#e66767',
      },
      boxShadow: {
        // Depth on dark = darker below + a whisper of light on the top edge.
        card: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 1px 2px rgba(0,0,0,.5), 0 8px 24px -8px rgba(0,0,0,.6)',
        pop: '0 1px 0 0 rgba(255,255,255,0.05) inset, 0 12px 32px rgba(0,0,0,.55), 0 32px 80px -16px rgba(0,0,0,.6)',
        'glow-brand': '0 0 0 1px rgba(57,135,229,.35), 0 0 24px -6px rgba(57,135,229,.45)',
        glass: '0 8px 40px rgba(0,0,0,.5)',
        glow: '0 0 0 1px rgba(255,255,255,.06), 0 14px 50px rgba(0,0,0,.6)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(.97)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        'fade-up': 'fade-up .4s cubic-bezier(.21,1.02,.73,1) both',
        shimmer: 'shimmer 1.8s linear infinite',
        'scale-in': 'scale-in .18s cubic-bezier(.21,1.02,.73,1) both',
      },
    },
  },
  plugins: [],
}
