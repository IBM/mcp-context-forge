/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./mcpgateway/templates/**/*.html",
        "./mcpgateway/static/**/*.js",
    ],
    darkMode: "class",
    theme: {
        extend: {
            animation: {
                "gradient-x": "gradient-x 15s ease infinite",
                float: "float 6s ease-in-out infinite",
                "pulse-soft": "pulse-soft 2s ease-in-out infinite",
                "slide-up": "slide-up 0.8s ease-out",
                "fade-in": "fade-in 1s ease-out",
                "scale-pulse": "scale-pulse 4s ease-in-out infinite",
            },
            keyframes: {
                "gradient-x": {
                    "0%, 100%": {
                        "background-size": "200% 200%",
                        "background-position": "left center",
                    },
                    "50%": {
                        "background-size": "200% 200%",
                        "background-position": "right center",
                    },
                },
                float: {
                    "0%, 100%": { transform: "translateY(0px)" },
                    "50%": { transform: "translateY(-20px)" },
                },
                "pulse-soft": {
                    "0%, 100%": { opacity: "1" },
                    "50%": { opacity: "0.8" },
                },
                "slide-up": {
                    "0%": { transform: "translateY(30px)", opacity: "0" },
                    "100%": { transform: "translateY(0)", opacity: "1" },
                },
                "fade-in": {
                    "0%": { opacity: "0" },
                    "100%": { opacity: "1" },
                },
                "scale-pulse": {
                    "0%, 100%": { transform: "scale(1)" },
                    "50%": { transform: "scale(1.05)" },
                },
            },
        },
    },
    plugins: [],
};
