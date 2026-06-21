import { useCallback, useEffect, useRef, useState } from "react";
import { Tooltip } from "@fluentui/react-components";

import styles from "./ScrollToBottomButton.module.css";

interface ScrollToBottomButtonProps {
    /** Ref to the scrollable chat container (the `.chatContainer` element). */
    containerRef: React.RefObject<HTMLElement | null>;
    /**
     * How far (in px) the user must be scrolled up from the bottom before the
     * button appears. Mirrors the small ChatGPT-style hysteresis.
     */
    threshold?: number;
    /** Accessible label / tooltip for the button. */
    ariaLabel?: string;
}

/**
 * Floating "jump to latest message" control, modeled on ChatGPT's down-arrow.
 *
 * Self-contained: it watches the passed scroll container (scroll + content
 * growth + viewport resize) and reveals itself only when the user has scrolled
 * up beyond `threshold`. It is meant to be rendered inside the sticky
 * `.chatInput` composer, which is the positioning context it anchors to, so no
 * per-bot CSS is required.
 */
export const ScrollToBottomButton = ({
    containerRef,
    threshold = 240,
    ariaLabel = "Scroll to latest message"
}: ScrollToBottomButtonProps) => {
    const [visible, setVisible] = useState(false);
    const rafRef = useRef<number | null>(null);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return;
        }

        const update = () => {
            const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
            setVisible(distanceFromBottom > threshold);
        };

        // Coalesce the bursts of scroll/mutation events fired while streaming.
        const scheduleUpdate = () => {
            if (rafRef.current != null) {
                return;
            }
            rafRef.current = window.requestAnimationFrame(() => {
                rafRef.current = null;
                update();
            });
        };

        update();
        container.addEventListener("scroll", scheduleUpdate, { passive: true });
        window.addEventListener("resize", scheduleUpdate);
        // Content growth (streamed tokens, new messages) changes scrollHeight
        // without firing a scroll event, so observe the subtree too.
        const resizeObserver = new ResizeObserver(scheduleUpdate);
        resizeObserver.observe(container);
        const mutationObserver = new MutationObserver(scheduleUpdate);
        mutationObserver.observe(container, { childList: true, subtree: true, characterData: true });

        return () => {
            container.removeEventListener("scroll", scheduleUpdate);
            window.removeEventListener("resize", scheduleUpdate);
            resizeObserver.disconnect();
            mutationObserver.disconnect();
            if (rafRef.current != null) {
                window.cancelAnimationFrame(rafRef.current);
                rafRef.current = null;
            }
        };
    }, [containerRef, threshold]);

    const scrollToBottom = useCallback(() => {
        const container = containerRef.current;
        if (!container) {
            return;
        }
        container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }, [containerRef]);

    // Fluent v9 Tooltip → the shared `.fui-Tooltip__content` dark pill, matching the
    // other icon-button tooltips. The trigger is a real DOM <button>, so the Tooltip
    // anchors to it directly (no <span> wrapper as the v8 IconButtons need).
    return (
        <Tooltip content={ariaLabel} relationship="label" showDelay={0} hideDelay={0}>
            <button
                type="button"
                className={`${styles.scrollButton} ${visible ? styles.visible : ""}`}
                onClick={scrollToBottom}
                aria-label={ariaLabel}
                aria-hidden={!visible}
                tabIndex={visible ? 0 : -1}
            >
                <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false">
                    <path
                        d="M8 2.75v10.5M8 13.25l4.25-4.25M8 13.25 3.75 9"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    />
                </svg>
            </button>
        </Tooltip>
    );
};

export default ScrollToBottomButton;
