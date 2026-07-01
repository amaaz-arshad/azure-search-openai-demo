import { createContext, useContext } from "react";

import type { BotConfig } from "../../api/models";

// Runtime identity for a dynamically provisioned bot, provided by GenericChatbotRoute after it resolves
// /bot-config/<botName>. The forked lemon Layout + Chat read from this instead of lemon's hardcoded
// "lemon" identity, so the exact same component tree renders for any provisioned bot.
export const BotConfigContext = createContext<BotConfig | null>(null);

export function useBotConfig(): BotConfig {
    const config = useContext(BotConfigContext);
    if (!config) {
        throw new Error("useBotConfig must be used within a BotConfigContext provider");
    }
    return config;
}
