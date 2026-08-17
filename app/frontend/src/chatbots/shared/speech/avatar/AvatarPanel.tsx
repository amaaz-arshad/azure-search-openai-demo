import { RefObject } from "react";
import { Button, Tooltip } from "@fluentui/react-components";
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
    interimTranscript?: string;
    onInterrupt?: () => void;
}

/**
 * The floating avatar video panel.
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
    interimTranscript = "",
    onInterrupt
}: Props) => {
    const { t } = useTranslation();

    const closeLabel = t("avatar.close");
    const conversational = Boolean(onInterrupt);

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
        <div className={`${styles.panel} ${hidden ? styles.panelHidden : ""}`} data-testid="avatar-panel" aria-hidden={hidden}>
            <div className={styles.videoWrapper}>
                {/* muted: the audio track plays through the <audio> element below, so leaving the
                    video element unmuted would double the sound on browsers that mix both. */}
                <video ref={videoRef} className={styles.video} autoPlay playsInline muted />
                <audio ref={audioRef} autoPlay />
                {status === "connecting" && <div className={styles.statusOverlay}>{t("avatar.connecting")}</div>}
                {status === "error" && <div className={styles.errorOverlay}>{error || t("avatar.error")}</div>}
            </div>

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

            <div className={styles.footer}>
                <p className={styles.disclosure}>{t("avatar.disclosure")}</p>
                <Tooltip content={closeLabel} relationship="label">
                    <Button appearance="subtle" icon={<Dismiss24Regular />} aria-label={closeLabel} onClick={onClose} />
                </Tooltip>
            </div>
        </div>
    );
};
