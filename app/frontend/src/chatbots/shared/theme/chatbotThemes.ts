import type { CSSProperties } from "react";

type ThemeColorPair = {
    background: string;
    text: string;
};

type ThemeGradient = {
    start: string;
    mid?: string;
    end?: string;
};

export type ChatbotTheme = {
    navbar: ThemeColorPair;
    loginButton: ThemeColorPair;
    loginPage: {
        background: ThemeGradient;
        button: ThemeColorPair;
    };
    userBubble: ThemeColorPair;
};

type DeepPartial<T> = {
    [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K];
};

export type ChatbotThemeSeed = {
    primary: string;
    loginButtonStyle?: "surface" | "solid";
    pageTone?: "auto" | "light" | "dark";
    overrides?: DeepPartial<ChatbotTheme>;
};

const defaultThemeSeed: ChatbotThemeSeed = {
    primary: "#4b5563"
};

// Most chatbots only need a single primary color here.
// The rest of the navbar/login/page/bubble theme is derived automatically.
// If one chatbot needs a special case later, use the optional `overrides`.
export const chatbotThemes: Record<string, ChatbotThemeSeed> = {
    agindo: {
        primary: "#e2c200",
        pageTone: "light"
    },
    bensberg: {
        primary: "#005155",
        pageTone: "light",
        overrides: {
            navbar: {
                text: "#96f0eb"
            },
            userBubble: {
                background: "#96f0eb",
                text: "#005155"
            }
        }
    },
    cbtx: {
        primary: "#910F3F",
        pageTone: "light"
    },
    demo: {
        primary: "#313335",
        pageTone: "light"
    },
    fbn: {
        primary: "#00cc96",
        pageTone: "light"
    },
    fhg: {
        primary: "#669d24",
        pageTone: "light"
    },
    "hyrox-assessment": {
        // HYROX highlight colour; the visible chrome is black with yellow accents.
        primary: "#FFED00",
        pageTone: "light",
        overrides: {
            navbar: {
                background: "#000000",
                text: "#FFED00"
            },
            userBubble: {
                background: "#ffffff",
                text: "#000000"
            }
        }
    },
    internal: {
        primary: "#313335",
        pageTone: "light"
    },
    knoll: {
        primary: "#0199fe",
        pageTone: "light",
        loginButtonStyle: "solid",
        overrides: {
            navbar: {
                text: "#ffffff"
            },
            loginButton: {
                text: "#ffffff"
            },
            loginPage: {
                button: {
                    text: "#ffffff"
                }
            }
        }
    },
    lemon: {
        primary: "#fec701",
        pageTone: "light"
    },
    moodle: {
        primary: "#f98012",
        pageTone: "light"
    },
    nerilio: {
        primary: "#ac44c6",
        pageTone: "light"
    },
    snap: {
        primary: "#ac44c6",
        pageTone: "light"
    },
    free: {
        primary: "#AC44C6",
        pageTone: "light"
    },
    publishone: {
        primary: "#003144",
        pageTone: "light"
    },
    rak: {
        primary: "#e30613",
        pageTone: "light"
    },
    sartorius: {
        primary: "#ffed00",
        pageTone: "light"
    },
    steuertipps: {
        primary: "#ffe016",
        pageTone: "light"
    },
    vjoonk4: {
        primary: "#00cc96",
        pageTone: "light"
    }
};

function clampColorChannel(value: number): number {
    return Math.max(0, Math.min(255, Math.round(value)));
}

function hexToRgb(color: string): { r: number; g: number; b: number } | null {
    const normalized = color.trim();
    const shortHexMatch = /^#([\da-f]{3})$/i.exec(normalized);
    if (shortHexMatch) {
        const [r, g, b] = shortHexMatch[1].split("");
        return {
            r: Number.parseInt(`${r}${r}`, 16),
            g: Number.parseInt(`${g}${g}`, 16),
            b: Number.parseInt(`${b}${b}`, 16)
        };
    }

    const fullHexMatch = /^#([\da-f]{6})$/i.exec(normalized);
    if (!fullHexMatch) {
        return null;
    }

    return {
        r: Number.parseInt(fullHexMatch[1].slice(0, 2), 16),
        g: Number.parseInt(fullHexMatch[1].slice(2, 4), 16),
        b: Number.parseInt(fullHexMatch[1].slice(4, 6), 16)
    };
}

function rgbToHex(r: number, g: number, b: number): string {
    return `#${[r, g, b]
        .map(channel => clampColorChannel(channel).toString(16).padStart(2, "0"))
        .join("")}`;
}

function mixColors(color: string, target: string, amount: number): string {
    const sourceRgb = hexToRgb(color);
    const targetRgb = hexToRgb(target);
    if (!sourceRgb || !targetRgb) {
        return color;
    }

    return rgbToHex(
        sourceRgb.r + (targetRgb.r - sourceRgb.r) * amount,
        sourceRgb.g + (targetRgb.g - sourceRgb.g) * amount,
        sourceRgb.b + (targetRgb.b - sourceRgb.b) * amount
    );
}

function darken(color: string, amount: number): string {
    return mixColors(color, "#000000", amount);
}

function lighten(color: string, amount: number): string {
    return mixColors(color, "#ffffff", amount);
}

function withAlpha(color: string, alpha: number): string {
    const rgb = hexToRgb(color);
    if (!rgb) {
        return color;
    }

    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

function getRelativeLuminance(color: string): number {
    const rgb = hexToRgb(color);
    if (!rgb) {
        return 0;
    }

    const normalize = (channel: number) => {
        const value = channel / 255;
        return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };

    const r = normalize(rgb.r);
    const g = normalize(rgb.g);
    const b = normalize(rgb.b);

    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function getContrastRatio(foreground: string, background: string): number {
    const foregroundLuminance = getRelativeLuminance(foreground);
    const backgroundLuminance = getRelativeLuminance(background);
    const lighter = Math.max(foregroundLuminance, backgroundLuminance);
    const darker = Math.min(foregroundLuminance, backgroundLuminance);

    return (lighter + 0.05) / (darker + 0.05);
}

function getReadableText(background: string): string {
    const whiteContrast = getContrastRatio("#ffffff", background);
    const blackContrast = getContrastRatio("#000000", background);
    return whiteContrast >= blackContrast ? "#ffffff" : "#000000";
}

function getReadableTextForGradient(gradient: ThemeGradient): string {
    const stops = [gradient.start, gradient.mid, gradient.end].filter((color): color is string => Boolean(color));
    const whiteContrast = Math.min(...stops.map(color => getContrastRatio("#ffffff", color)));
    const darkText = "#111827";
    const darkContrast = Math.min(...stops.map(color => getContrastRatio(darkText, color)));

    return whiteContrast >= darkContrast ? "#ffffff" : darkText;
}

function isDark(color: string): boolean {
    return getRelativeLuminance(color) < 0.28;
}

function createSurfaceColor(primary: string): string {
    return lighten(primary, isDark(primary) ? 0.88 : 0.94);
}

function shiftHoverColor(color: string): string {
    return isDark(color) ? lighten(color, 0.08) : darken(color, 0.08);
}

function createPageGradient(primary: string, pageTone: ChatbotThemeSeed["pageTone"]): ThemeGradient {
    const tone = pageTone === "auto" || pageTone === undefined ? (isDark(primary) ? "dark" : "light") : pageTone;

    if (tone === "dark") {
        return {
            start: darken(primary, 0.12),
            mid: primary,
            end: lighten(primary, 0.08)
        };
    }

    return {
        start: lighten(primary, 0.92),
        mid: lighten(primary, 0.78),
        end: lighten(primary, 0.62)
    };
}

function createUserBubbleGradient(primary: string): ThemeGradient {
    if (getReadableText(primary) === "#ffffff") {
        return {
            start: darken(primary, 0.12),
            end: primary
        };
    }

    return {
        start: lighten(primary, 0.06),
        end: darken(primary, 0.08)
    };
}

function toLinearGradient(gradient: ThemeGradient): string {
    const midStop = gradient.mid ? `${gradient.mid} 52%, ` : "";
    const end = gradient.end ?? gradient.mid ?? gradient.start;

    return `linear-gradient(135deg, ${gradient.start} 0%, ${midStop}${end} 100%)`;
}

function mergeTheme(base: ChatbotTheme, overrides?: DeepPartial<ChatbotTheme>): ChatbotTheme {
    if (!overrides) {
        return base;
    }

    return {
        navbar: {
            ...base.navbar,
            ...overrides.navbar
        },
        loginButton: {
            ...base.loginButton,
            ...overrides.loginButton
        },
        loginPage: {
            background: {
                ...base.loginPage.background,
                ...overrides.loginPage?.background
            },
            button: {
                ...base.loginPage.button,
                ...overrides.loginPage?.button
            }
        },
        userBubble: {
            ...base.userBubble,
            ...overrides.userBubble
        }
    };
}

function resolveChatbotTheme(seed: ChatbotThemeSeed): ChatbotTheme {
    const primaryText = getReadableText(seed.primary);
    const loginButtonBackground = seed.loginButtonStyle === "solid" ? seed.primary : createSurfaceColor(seed.primary);
    const userBubbleGradient = createUserBubbleGradient(seed.primary);

    const baseTheme: ChatbotTheme = {
        navbar: {
            background: seed.primary,
            text: primaryText
        },
        loginButton: {
            background: loginButtonBackground,
            text: getReadableText(loginButtonBackground)
        },
        loginPage: {
            background: createPageGradient(seed.primary, seed.pageTone),
            button: {
                background: seed.primary,
                text: primaryText
            }
        },
        userBubble: {
            background: toLinearGradient(userBubbleGradient),
            text: getReadableTextForGradient(userBubbleGradient)
        }
    };

    return mergeTheme(baseTheme, seed.overrides);
}

export function getChatbotTheme(chatbotName: string): ChatbotTheme {
    return resolveChatbotTheme(chatbotThemes[chatbotName] ?? defaultThemeSeed);
}

export function getChatbotThemeCssVariables(chatbotName: string): CSSProperties {
    return cssVariablesFromTheme(getChatbotTheme(chatbotName));
}

// Theme a dynamically provisioned bot from a runtime seed (e.g. just a primary color) instead of the
// static chatbotThemes map. Built-in bots never reach this — they go through the name lookup above.
export function getChatbotThemeCssVariablesFromSeed(seed: ChatbotThemeSeed): CSSProperties {
    return cssVariablesFromTheme(resolveChatbotTheme(seed));
}

function cssVariablesFromTheme(theme: ChatbotTheme): CSSProperties {
    const loginPageButton = theme.loginPage.button;
    const loginPageBackground = theme.loginPage.background;
    const disclaimerBackground = lighten(theme.navbar.background, isDark(theme.navbar.background) ? 0.9 : 0.95);
    const disclaimerText = getReadableText(disclaimerBackground);
    const disclaimerAccent = isDark(theme.navbar.background) ? theme.navbar.background : darken(theme.navbar.background, 0.38);

    return {
        "--chatbot-navbar-background": theme.navbar.background,
        "--chatbot-navbar-text": theme.navbar.text,
        "--chatbot-navbar-logo-background": "#ffffff",
        "--chatbot-navbar-menu-hover-background": withAlpha(theme.navbar.text, 0.1),
        "--chatbot-dropdown-background": "#ffffff",
        "--chatbot-dropdown-border": withAlpha(theme.navbar.background, 0.16),
        "--chatbot-dropdown-shadow": `0 12px 28px ${withAlpha(theme.navbar.background, 0.16)}`,
        "--chatbot-dropdown-item-text": "#182033",
        "--chatbot-dropdown-item-hover-background": withAlpha(theme.navbar.background, 0.08),
        "--chatbot-login-button-background": theme.loginButton.background,
        "--chatbot-login-button-text": theme.loginButton.text,
        "--chatbot-login-button-border": withAlpha(theme.loginButton.text, 0.14),
        "--chatbot-login-button-hover-background": shiftHoverColor(theme.loginButton.background),
        "--chatbot-login-button-hover-text": theme.loginButton.text,
        "--chatbot-login-button-hover-border": withAlpha(theme.loginButton.text, 0.22),
        "--chatbot-login-button-focus-ring": withAlpha(theme.loginButton.background, 0.24),
        "--chatbot-user-bubble-background": theme.userBubble.background,
        "--chatbot-user-bubble-text": theme.userBubble.text,
        "--chatbot-disclaimer-background": disclaimerBackground,
        "--chatbot-disclaimer-border": withAlpha(theme.navbar.background, 0.18),
        "--chatbot-disclaimer-shadow": `0 16px 36px ${withAlpha(theme.navbar.background, 0.12)}`,
        "--chatbot-disclaimer-text": disclaimerText,
        "--chatbot-disclaimer-accent": disclaimerAccent,
        "--chatbot-disclaimer-dismiss-background": withAlpha(theme.navbar.background, 0.08),
        "--chatbot-disclaimer-dismiss-hover-background": withAlpha(theme.navbar.background, 0.16),
        "--chatbot-disclaimer-dismiss-text": disclaimerText,
        "--login-accent": loginPageButton.background,
        "--login-accent-dark": darken(loginPageButton.background, 0.22),
        "--login-accent-soft": withAlpha(loginPageButton.background, 0.18),
        "--login-highlight-soft": withAlpha(lighten(loginPageButton.background, 0.4), 0.2),
        "--login-page-start": loginPageBackground.start,
        "--login-page-mid": loginPageBackground.mid ?? loginPageBackground.start,
        "--login-page-end": loginPageBackground.end ?? loginPageBackground.mid ?? loginPageBackground.start,
        "--login-panel-border": withAlpha(loginPageButton.background, 0.14),
        "--login-input-border": withAlpha(loginPageButton.background, 0.18),
        "--login-input-focus": withAlpha(loginPageButton.background, 0.4),
        "--login-focus-ring": withAlpha(loginPageButton.background, 0.14),
        "--login-focus-ring-strong": withAlpha(loginPageButton.background, 0.28),
        "--login-text-strong": "#202225",
        "--login-text-muted": "#5e6670",
        "--login-text-placeholder": "#7e8791",
        "--login-logo-surface": "rgba(255, 255, 255, 0.84)",
        "--login-card-background": "rgba(255, 255, 255, 0.86)",
        "--login-card-shadow": isDark(loginPageButton.background) ? "rgba(0, 0, 0, 0.22)" : "rgba(15, 23, 42, 0.12)",
        "--login-button-text": loginPageButton.text,
        "--login-button-shadow": withAlpha(loginPageButton.background, 0.24),
        "--login-button-shadow-strong": withAlpha(darken(loginPageButton.background, 0.18), 0.3)
    } as CSSProperties;
}
