import path from "node:path";
import { defineConfig } from "vite";

// Builds the standalone, dependency-free embeddable loader into the backend static root as
// `widget.js`. Run AFTER the main `vite build` (whose emptyOutDir wipes the folder) by chaining
// it in package.json: `tsc && vite build && vite build --config vite.widget.config.ts`.
export default defineConfig({
    build: {
        outDir: "../backend/static",
        emptyOutDir: false,
        sourcemap: false,
        target: "es2018",
        lib: {
            entry: path.resolve(__dirname, "src/widget/widget.ts"),
            name: "ChatbotWidget",
            formats: ["iife"],
            fileName: () => "widget.js"
        }
    }
});
