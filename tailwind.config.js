/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        ost: {
          bg: '#0c0e12',
          panel: '#12151c',
          border: '#252a35',
          accent: '#3b82f6',
          muted: '#8b93a7',
        },
      },
    },
  },
  plugins: [],
};
