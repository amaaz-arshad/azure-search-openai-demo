import type { PropsWithChildren } from "react";

import { getChatbotThemeCssVariables, getChatbotThemeCssVariablesFromSeed, type ChatbotThemeSeed } from "./chatbotThemes";
import styles from "./ChatbotThemeRoot.module.css";

type ChatbotThemeRootProps = PropsWithChildren<{
    chatbotName: string;
    embed?: boolean;
    // When provided (dynamic/provisioned bots), derive the theme from this runtime seed instead of the
    // static chatbotThemes map. Built-in bots omit it, so their theming is byte-for-byte unchanged.
    seed?: ChatbotThemeSeed;
}>;

export function ChatbotThemeRoot({ chatbotName, embed, seed, children }: ChatbotThemeRootProps) {
    const style = seed ? getChatbotThemeCssVariablesFromSeed(seed) : getChatbotThemeCssVariables(chatbotName);
    return (
        <div className={styles.root} data-chatbot-theme={chatbotName} data-embed={embed ? "1" : undefined} style={style}>
            {children}
        </div>
    );
}
