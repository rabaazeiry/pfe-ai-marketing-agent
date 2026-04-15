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
      },
      keyframes: {
        'toast-in': {
          '0%': { opacity: '0', transform: 'translateY(8px) scale(0.98)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' }
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' }
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' }
        }
      },
      animation: {
        'toast-in': 'toast-in 180ms ease-out',
        'fade-in': 'fade-in 160ms ease-out',
        shimmer: 'shimmer 1.4s linear infinite'
      }
    }
  },
  plugins: [require('tailwindcss-rtl')]
};
