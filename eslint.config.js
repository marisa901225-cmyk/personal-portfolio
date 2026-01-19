import js from "@eslint/js";
import tseslint from "typescript-eslint";
import globals from "globals";

export default tseslint.config(
    {
        ignores: [
            "**/dist/**",
            "**/node_modules/**",
            "**/venv/**",
            "**/.venv/**",
            "**/*.pyc",
            "**/__pycache__/**",
            "**/.output/**",
            "**/build/**",
            "**/out/**"
        ]
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
        files: ["**/*.{ts,tsx}"],
        languageOptions: {
            globals: {
                ...globals.browser,
                ...globals.node
            }
        },
        rules: {
            "@typescript-eslint/no-explicit-any": "error",
            "@typescript-eslint/no-unused-vars": "warn",
            "no-undef": "error"
        },
    },
    {
        files: ["**/types.ts"],
        rules: {
            "@typescript-eslint/no-explicit-any": "off"
        }
    }
);
