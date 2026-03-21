import type { PropsWithChildren } from "react";

import { getChatbotThemeCssVariables } from "./chatbotThemes";
import styles from "./ChatbotThemeRoot.module.css";

type ChatbotThemeRootProps = PropsWithChildren<{
    chatbotName: string;
}>;

export function ChatbotThemeRoot({ chatbotName, children }: ChatbotThemeRootProps) {
    return (
        <div className={styles.root} data-chatbot-theme={chatbotName} style={getChatbotThemeCssVariables(chatbotName)}>
            {children}
        </div>
    );
}
