import { useEffect, useState } from "react";

// The chat-history panel switches from a side-by-side push to a modal drawer
// (with a dimmed backdrop) below this width. Keep in sync with the 992px
// breakpoint used for `.chatRootHistoryOpen` in each chatbot's Chat.module.css.
const COMPACT_VIEWPORT_QUERY = "(max-width: 991.98px)";

const getMatches = (): boolean => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
        return false;
    }
    return window.matchMedia(COMPACT_VIEWPORT_QUERY).matches;
};

// Returns true on compact viewports so callers can present a modal/overlay
// instead of a layout that pushes content aside. Reactive to viewport changes
// (resize, orientation) while mounted.
export const useIsCompactViewport = (): boolean => {
    const [isCompact, setIsCompact] = useState<boolean>(getMatches);

    useEffect(() => {
        if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
            return;
        }
        const mediaQuery = window.matchMedia(COMPACT_VIEWPORT_QUERY);
        const handleChange = (event: MediaQueryListEvent) => setIsCompact(event.matches);
        setIsCompact(mediaQuery.matches);
        mediaQuery.addEventListener("change", handleChange);
        return () => mediaQuery.removeEventListener("change", handleChange);
    }, []);

    return isCompact;
};
