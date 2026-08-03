export interface ChatbotSpeechVisibility {
    showSpeechInput: boolean;
    showSpeechOutputBrowser: boolean;
    showSpeechOutputAzure: boolean;
}

export type ChatbotSpeechConfig = {
    showSpeechInput: boolean;
    showSpeechOutputBrowser: boolean;
    showSpeechOutputAzure: boolean;
};

// Central place to enable/disable chatbot speech UI without editing component JSX.
// `true` means "allow the UI if the backend config also enables it".
// `false` means "hide the UI for this chatbot even if the backend enables it".
export const chatbotSpeechFeatureFlags: Record<string, ChatbotSpeechVisibility> = {
    agindo: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    bbsa: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    cbtx: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    demo: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    fbn: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    fhg: {
        showSpeechInput: false,
        showSpeechOutputBrowser: false,
        showSpeechOutputAzure: false
    },
    internal: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    knoll: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    lemon: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    moodle: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    nerilio: {
        showSpeechInput: false,
        showSpeechOutputBrowser: false,
        showSpeechOutputAzure: false
    },
    snap: {
        showSpeechInput: false,
        showSpeechOutputBrowser: false,
        showSpeechOutputAzure: false
    },
    free: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    rak: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    publishone: {
        showSpeechInput: false,
        showSpeechOutputBrowser: false,
        showSpeechOutputAzure: false
    },
    sartorius: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    steuertipps: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    },
    vjoonk4: {
        showSpeechInput: true,
        showSpeechOutputBrowser: true,
        showSpeechOutputAzure: true
    }
};

export function applyChatbotSpeechFeatureFlags<T extends ChatbotSpeechConfig>(chatbotName: string, config: T): T {
    const flags = chatbotSpeechFeatureFlags[chatbotName];
    if (!flags) {
        return config;
    }

    return {
        ...config,
        showSpeechInput: config.showSpeechInput && flags.showSpeechInput,
        showSpeechOutputBrowser: config.showSpeechOutputBrowser && flags.showSpeechOutputBrowser,
        showSpeechOutputAzure: config.showSpeechOutputAzure && flags.showSpeechOutputAzure
    };
}
