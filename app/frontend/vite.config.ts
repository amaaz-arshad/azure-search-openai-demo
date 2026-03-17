import fs from "node:fs";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const repoRoot = path.resolve(__dirname, "../..");
const azureConfigPath = path.resolve(repoRoot, ".azure/config.json");

const getAzdEnvDir = () => {
    const explicitEnvName = process.env.AZD_ENV_NAME || process.env.AZURE_ENV_NAME;
    if (explicitEnvName) {
        return path.resolve(repoRoot, `.azure/${explicitEnvName}`);
    }

    if (!fs.existsSync(azureConfigPath)) {
        return undefined;
    }

    try {
        const azureConfig = JSON.parse(fs.readFileSync(azureConfigPath, "utf-8")) as { defaultEnvironment?: string };
        if (azureConfig.defaultEnvironment) {
            return path.resolve(repoRoot, `.azure/${azureConfig.defaultEnvironment}`);
        }
    } catch {
        // Fall back to regular Vite env handling if the AZD config cannot be parsed.
    }

    return undefined;
};

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const azdEnvDir = getAzdEnvDir();
    const azdEnv = azdEnvDir && fs.existsSync(azdEnvDir) ? loadEnv(mode, azdEnvDir, "") : {};

    return {
        plugins: [react()],
        define: {
            "import.meta.env.VITE_AZURE_SPEECH_SERVICE_LOCATION": JSON.stringify(azdEnv.AZURE_SPEECH_SERVICE_LOCATION ?? ""),
            "import.meta.env.VITE_AZURE_SPEECH_SERVICE_VOICE": JSON.stringify(azdEnv.AZURE_SPEECH_SERVICE_VOICE ?? ""),
            "import.meta.env.VITE_AZURE_SPEECH_SERVICE_API_KEY": JSON.stringify(azdEnv.AZURE_SPEECH_SERVICE_API_KEY ?? "")
        },
        resolve: {
            preserveSymlinks: true
        },
        build: {
            outDir: "../backend/static",
            emptyOutDir: true,
            sourcemap: true,
            rollupOptions: {
                output: {
                    manualChunks: id => {
                        if (id.includes("@fluentui/react-icons")) {
                            return "fluentui-icons";
                        } else if (id.includes("@fluentui/react")) {
                            return "fluentui-react";
                        } else if (id.includes("node_modules")) {
                            return "vendor";
                        }
                    }
                }
            },
            target: "esnext"
        },
        server: {
            proxy: {
                "/content/": "http://localhost:50505",
                "/auth_setup": "http://localhost:50505",
                "/.auth/me": "http://localhost:50505",
                "/chat": "http://localhost:50505",
                "/speech": "http://localhost:50505",
                "/config": "http://localhost:50505",
                "/chatbot_uploads": "http://localhost:50505",
                "/upload": "http://localhost:50505",
                "/delete_uploaded": "http://localhost:50505",
                "/list_uploaded": "http://localhost:50505",
                "/chat_history": "http://localhost:50505"
            }
        }
    };
});
