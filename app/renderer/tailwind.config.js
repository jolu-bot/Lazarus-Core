/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      { DEFAULT: '#0A0A0F', 2: '#12121A', 3: '#1A1A26' },
        surface: { DEFAULT: '#16161F', 2: '#1E1E2E', border: '#2A2A3E' },
        primary: { DEFAULT: '#6C63FF', hover: '#7D75FF', glow: '#6C63FF33' },
        accent:  { DEFAULT: '#FF6B6B', green: '#4ECDC4', yellow: '#FFE66D' },
        text:    { DEFAULT: '#E8E8F0', muted: '#8888A8', dim: '#55556A' },
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
