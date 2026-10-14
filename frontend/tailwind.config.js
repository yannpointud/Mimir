/** @type {import('tailwindcss').Config} */

// Every brand color resolves to a CSS variable declared in src/index.css, so a
// customer palette is swapped by editing one :root block, without a rebuild of
// the component classes.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: token('canvas'),
        surface: token('surface'),
        sunken: token('sunken'),
        ink: {
          DEFAULT: token('ink'),
          muted: token('ink-muted'),
          faint: token('ink-faint'),
        },
        line: {
          DEFAULT: token('line'),
          soft: token('line-soft'),
          strong: token('line-strong'),
        },
        accent: {
          DEFAULT: token('accent'),
          hover: token('accent-hover'),
          soft: token('accent-soft'),
          ink: token('accent-ink'),
          on: token('on-accent'),
          bright: token('accent-bright'),
        },
        nav: {
          DEFAULT: token('nav'),
          ink: token('nav-ink'),
          muted: token('nav-muted'),
          raised: token('nav-raised'),
        },
        hl: {
          DEFAULT: token('hl'),
          soft: token('hl-soft'),
        },
        success: {
          DEFAULT: token('success'),
          soft: token('success-soft'),
          ink: token('success-ink'),
        },
        warning: {
          DEFAULT: token('warning'),
          soft: token('warning-soft'),
          ink: token('warning-ink'),
        },
        danger: {
          DEFAULT: token('danger'),
          hover: token('danger-hover'),
          soft: token('danger-soft'),
          ink: token('danger-ink'),
        },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        serif: ['"Source Serif 4 Variable"', 'Georgia', 'ui-serif', 'serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        xs: '0 1px 2px rgb(16 32 48 / 0.06)',
        card: '0 1px 2px rgb(16 32 48 / 0.04), 0 1px 3px rgb(16 32 48 / 0.06)',
        raised: '0 12px 32px -12px rgb(15 30 45 / 0.22), 0 2px 6px rgb(15 30 45 / 0.06)',
        modal: '0 28px 72px -18px rgb(15 30 45 / 0.42), 0 4px 12px rgb(15 30 45 / 0.08)',
        focus: '0 0 0 3px rgb(var(--accent) / 0.18)',
      },
      maxWidth: {
        prose: '46rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.18s ease-out',
        'slide-up': 'slideUp 0.24s cubic-bezier(0.16, 1, 0.3, 1)',
        'pop-in': 'popIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
        'caret': 'caret 1s steps(1) infinite',
        'dot': 'dot 1.2s ease-in-out infinite',
        'indeterminate': 'indeterminate 1.2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        popIn: {
          '0%': { transform: 'translateY(6px) scale(0.98)', opacity: '0' },
          '100%': { transform: 'translateY(0) scale(1)', opacity: '1' },
        },
        caret: {
          '0%, 49%': { opacity: '1' },
          '50%, 100%': { opacity: '0' },
        },
        dot: {
          '0%, 80%, 100%': { opacity: '0.25', transform: 'translateY(0)' },
          '40%': { opacity: '1', transform: 'translateY(-2px)' },
        },
        indeterminate: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(300%)' },
        },
      },
    },
  },
  plugins: [],
}
