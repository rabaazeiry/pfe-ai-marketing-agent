/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef5ff',
          100: '#d9e7ff',
          200: '#bcd4ff',
          300: '#8eb8ff',
          400: '#5a91ff',
          500: '#3066f2',
          600: '#1d4ad4',
          700: '#173aa8',
          800: '#153185',
          900: '#142c6b'
        }
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        arabic: ['"Noto Sans Arabic"', '"Segoe UI"', 'Tahoma', 'sans-serif']
      },
      boxShadow: {
        soft: '0 6px 24px -12px rgba(16, 24, 40, 0.12)'
      }
    }
  },
  plugins: [require('tailwindcss-rtl')]
};
