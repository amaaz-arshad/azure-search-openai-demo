import type { PropsWithChildren } from "react";

import { getChatbotThemeCssVariables } from "./chatbotThemes";
import styles from "./ChatbotThemeRoot.module.css";

type ChatbotThemeRootProps = PropsWithChildren<{
    chatbotName: string;
    embed?: boolean;
}>;

export function ChatbotThemeRoot({ chatbotName, embed, children }: ChatbotThemeRootProps) {
    return (
        <div
            className={styles.root}
            data-chatbot-theme={chatbotName}
            data-embed={embed ? "1" : undefined}
            style={getChatbotThemeCssVariables(chatbotName)}
        >
            {children}
        </div>
    );
}
