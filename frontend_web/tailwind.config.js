/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  darkMode: ['selector', '[data-theme="dark"], html.dark'],
  theme: {
    extend: {
      colors: {
        primary: {
          50:  '#eef2ff',
          100: '#E8EEFB',
          500: '#1C64F2',
          600: '#1d4ed8',
          700: '#4338ca',
        },
      },
      boxShadow: {
        floating: '0 8px 30px rgba(0, 0, 0, 0.08)',
      },
      borderRadius: {
        xl2: '14px',
      },
    },
  },
  plugins: [],
};
