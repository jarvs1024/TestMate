/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  darkMode: ['selector', '[data-theme="dark"], html.dark'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'var(--primary)',
          hover:   'var(--primary-hover)',
          soft:    'var(--primary-soft)',
        },
      },
    },
  },
  plugins: [],
};
