/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Les couleurs sont des variables CSS (voir globals.css) : thème sombre/clair sans dupliquer les composants.
        bg:      { DEFAULT: 'rgb(var(--c-bg) / <alpha-value>)', 2: 'rgb(var(--c-bg-2) / <alpha-value>)', 3: 'rgb(var(--c-bg-3) / <alpha-value>)' },
        surface: { DEFAULT: 'rgb(var(--c-surface) / <alpha-value>)', 2: 'rgb(var(--c-surface-2) / <alpha-value>)', border: 'rgb(var(--c-border) / <alpha-value>)' },
        primary: { DEFAULT: 'rgb(var(--c-primary) / <alpha-value>)', hover: 'rgb(var(--c-primary-hover) / <alpha-value>)', glow: '#6C63FF33' },
        accent:  { DEFAULT: 'rgb(var(--c-accent) / <alpha-value>)', green: 'rgb(var(--c-green) / <alpha-value>)', yellow: 'rgb(var(--c-yellow) / <alpha-value>)' },
        text:    { DEFAULT: 'rgb(var(--c-text) / <alpha-value>)', muted: 'rgb(var(--c-text-muted) / <alpha-value>)', dim: 'rgb(var(--c-text-dim) / <alpha-value>)' },
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        glow:        '0 0 20px rgba(108,99,255,0.3)',
        'glow-sm':   '0 0 10px rgba(108,99,255,0.2)',
        panel:       '0 4px 24px rgba(0,0,0,0.5)',
      },
      animation: {
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'scan-line':  'scanLine 2s linear infinite',
        'fade-in':    'fadeIn 0.3s ease-out',
        'slide-up':   'slideUp 0.3s ease-out',
      },
      keyframes: {
        pulseGlow: {
          '0%,100%': { boxShadow: '0 0 10px rgba(108,99,255,0.3)' },
          '50%':     { boxShadow: '0 0 25px rgba(108,99,255,0.6)' },
        },
        scanLine: {
          '0%':   { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' },
        },
        fadeIn:  { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
};
