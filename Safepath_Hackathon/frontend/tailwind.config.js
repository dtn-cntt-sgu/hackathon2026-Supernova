/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      borderRadius: {
        liquid: "28px",
        spatial: "24px",
      },
      backdropSaturate: {
        liquid: "210%",
      },
      colors: {
        background: "var(--bg-primary)",
        foreground: "var(--text-primary)",

        // Light Cinematic 3D Palette
        canvas: {
          DEFAULT: "#F8FBFF",
          pure: "#FFFFFF",
          soft: "#E9F5FF",
          ice: "#BFE8F7",
          mist: "#EEF7FD",
        },
        brand: {
          blue: "#168BD2",
          "blue-hover": "#0E78B9",
          teal: "#18B6AD",
          "teal-hover": "#139B94",
          navy: "#142A3B",
          slate: "#607889",
        },
        signal: {
          warning: "#E8A13B",
          "warning-bg": "#FEF6EB",
          danger: "#E16B68",
          "danger-bg": "#FDF1F0",
          safe: "#18B6AD",
          "safe-bg": "#EDFAF8",
        },

        // Legacy Aliases for seamless component compatibility
        pearl: {
          50: "#FAFBFD",
          100: "#F8FBFF",
          200: "#EEF7FD",
          300: "#E9F5FF",
          400: "#BFE8F7",
        },
        ice: {
          50: "#F8FBFF",
          100: "#F0F9FE",
          200: "#E9F5FF",
          300: "#BFE8F7",
          400: "#80D2F0",
        },
        ink: {
          950: "#142A3B",
          900: "#142A3B",
          800: "#223C52",
          700: "#36536B",
          600: "#4D6980",
          500: "#607889",
          400: "#829AA8",
          300: "#B2C5D4",
        },
      },
      boxShadow: {
        glass: "0 12px 32px -4px rgba(22, 139, 210, 0.08), 0 4px 16px -2px rgba(20, 42, 59, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.95)",
        "glass-elevated": "0 24px 56px -8px rgba(22, 139, 210, 0.14), 0 8px 24px -4px rgba(20, 42, 59, 0.06), inset 0 1px 0 #FFFFFF",
        "glass-sm": "0 2px 10px 0 rgba(22, 139, 210, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.8)",
        "glow-blue": "0 0 24px 0 rgba(22, 139, 210, 0.35)",
        "glow-teal": "0 0 24px 0 rgba(24, 182, 173, 0.40)",
      },
      backdropBlur: {
        xs: "2px",
        spatial: "20px",
      },
      animation: {
        aurora: "aurora 75s linear infinite",
      },
      keyframes: {
        aurora: {
          from: {
            backgroundPosition: "50% 50%, 50% 50%",
          },
          to: {
            backgroundPosition: "350% 50%, 350% 50%",
          },
        },
      },
    },
  },
  plugins: [],
};
