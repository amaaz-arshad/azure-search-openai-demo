import { RefObject, useEffect } from "react";
import { Button, Spinner, Tooltip } from "@fluentui/react-components";
import { Dismiss24Regular, RecordStop24Filled } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

import styles from "./AvatarPanel.module.css";
import { AvatarSessionStatus } from "./avatarSession";

interface Props {
    status: AvatarSessionStatus;
    error: string | null;
    videoRef: RefObject<HTMLVideoElement>;
    audioRef: RefObject<HTMLAudioElement>;
    onClose: () => void;
    /** Hidden rather than unmounted while there is no session — see the comment below. */
    hidden?: boolean;
    /** Conversation mode: omit these and the panel is a plain speaking avatar. */
    isSpeaking?: boolean;
    isListening?: boolean;
    isBusy?: boolean;
    /** Connectivity is wobbling; the session is inside its recovery grace window. */
    isReconnecting?: boolean;
    interimTranscript?: string;
    onInterrupt?: () => void;
}

/**
 * The avatar video stage: a full-screen overlay covering the whole viewport, chat and navbar alike.
 *
 * Full screen rather than a corner panel because this is a conversation, not a decoration — at
 * thumbnail size the face carried none of the expression it is there for, and the user's attention
 * was split between a talking head and the text they could not read anyway. The overlay is
 * `position: fixed`, so it still contributes ZERO layout height: its host chat is sized
 * calc(100vh - 56px) and tests/e2e.py asserts the document never exceeds the viewport.
 *
 * The chrome is deliberately sparse and floats over the video — close top-right, the synthetic-media
 * disclosure top-left, whose-turn-is-it at the bottom — so nothing competes with the face.
 *
 * The media elements stay mounted for the whole life of the panel because `AvatarSession.start`
 * binds the WebRTC tracks to them directly — unmounting them mid-session would drop the video.
 * The audio element is separate from the video element on purpose: the service sends audio and
 * video as two tracks, and `ontrack` fires once for each.
 */
export const AvatarPanel = ({
    status,
    error,
    videoRef,
    audioRef,
    onClose,
    hidden = false,
    isSpeaking = false,
    isListening = false,
    isBusy = false,
    isReconnecting = false,
    interimTranscript = "",
    onInterrupt
}: Props) => {
    const { t } = useTranslation();

    const closeLabel = t("avatar.close");
    const conversational = Boolean(onInterrupt);

    // Escape closes it. A full-screen takeover has to offer the standard way out, and here that is
    // also the cheapest one: the session bills per second it stays open.
    useEffect(() => {
        if (hidden) {
            return;
        }

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                onClose();
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => {
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [hidden, onClose]);

    // Half-duplex means exactly one of these is true at a time, so a single line can carry the
    // whole state — and the user needs it: without a cue for "your turn" they talk over the
    // avatar while the microphone is still shut.
    // "speaking" is also a live session: `AvatarSession.speak` flips the session status while the
    // avatar talks, so gating this on "ready" alone made the whole status bar disappear for the
    // duration of every answer — exactly when the user most needs to be told it is not their turn.
    const sessionIsUp = status === "ready" || status === "speaking";

    let statusLine = "";
    if (conversational && sessionIsUp) {
        if (isSpeaking) {
            statusLine = t("avatar.speaking");
        } else if (isBusy) {
            statusLine = t("avatar.thinking");
        } else if (isListening) {
            statusLine = interimTranscript || t("avatar.listening");
        } else {
            statusLine = t("avatar.starting");
        }
    }

    return (
        <div
            className={`${styles.panel} ${hidden ? styles.panelHidden : ""}`}
            data-testid="avatar-panel"
            aria-hidden={hidden}
            role="dialog"
            aria-modal="true"
            aria-label={t("avatar.title")}
        >
            <div className={styles.videoWrapper}>
                {/* muted: the audio track plays through the <audio> element below, so leaving the
                    video element unmuted would double the sound on browsers that mix both. */}
                <video ref={videoRef} className={styles.video} autoPlay playsInline muted />
                <audio ref={audioRef} autoPlay />
                {/* Both states are a centred card, not a full-bleed wash: at this size a tinted
                    viewport reads as a broken page rather than as "the thing you opened has
                    something to tell you". */}
                {status === "connecting" && (
                    <div className={styles.noticeOverlay}>
                        <div className={styles.notice}>
                            <Spinner size="tiny" />
                            <span>{t("avatar.connecting")}</span>
                        </div>
                    </div>
                )}
                {status === "error" && (
                    <div className={styles.noticeOverlay}>
                        <div className={`${styles.notice} ${styles.noticeError}`}>{error || t("avatar.error")}</div>
                    </div>
                )}
                {/* A transient drop freezes the video on its last decoded frame, which is
                    indistinguishable from the app hanging. Say what is happening instead — and keep
                    the wash light so the face stays visible behind it: the session is recovering,
                    not gone. */}
                {isReconnecting && status !== "connecting" && status !== "error" && (
                    <div className={`${styles.noticeOverlay} ${styles.noticeOverlaySubtle}`}>
                        <div className={styles.notice}>
                            <Spinner size="tiny" />
                            <span>{t("avatar.reconnecting")}</span>
                        </div>
                    </div>
                )}
            </div>

            {/* Microsoft requires the synthetic nature of the avatar to be disclosed to users. */}
            <p className={styles.disclosure}>{t("avatar.disclosure")}</p>

            <Tooltip content={closeLabel} relationship="label" showDelay={0} hideDelay={0}>
                <button type="button" className={styles.closeButton} aria-label={closeLabel} onClick={onClose}>
                    <Dismiss24Regular />
                </button>
            </Tooltip>

            {statusLine && (
                <div className={styles.statusBar} data-testid="avatar-status" data-listening={isListening ? "1" : undefined}>
                    {isListening && !isSpeaking && !isBusy && <span className={styles.listeningDot} aria-hidden="true" />}
                    <span className={styles.statusText}>{statusLine}</span>
                    {isSpeaking && onInterrupt && (
                        <Tooltip content={t("avatar.interrupt")} relationship="label">
                            <Button
                                appearance="subtle"
                                size="small"
                                icon={<RecordStop24Filled />}
                                aria-label={t("avatar.interrupt")}
                                onClick={onInterrupt}
                            />
                        </Tooltip>
                    )}
                </div>
            )}
        </div>
    );
};
