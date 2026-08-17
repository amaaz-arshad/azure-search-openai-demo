import { Tooltip } from "@fluentui/react-components";
import { VideoPersonOff24Filled, VideoPersonSparkle24Filled } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

import styles from "./AvatarToggleButton.module.css";

interface Props {
    isActive: boolean;
    isBusy: boolean;
    onStart: () => void;
    onStop: () => void;
    className?: string;
}

/**
 * Launcher for the live avatar.
 *
 * Styled as a solid accent-coloured circle rather than one of the app's icon buttons, which is the
 * established shape for an assistant launcher and is what makes it read as a way in rather than as
 * a toolbar toggle.
 *
 * The glyph is `VideoPersonSparkle`: a person in a video frame, plus the sparkle that now
 * universally marks AI. That combination is doing real work — widget guidance is blunt that a
 * persona must not imply a human is present, and the sparkle is what keeps this honest while still
 * promising a face rather than a text box. `VideoPersonOff` mirrors it for the stop state.
 *
 * Starting is deliberately an explicit user action rather than something that happens on page
 * load: the session bills per minute of wall-clock time, and the bots that use this are ungated
 * and publicly embeddable.
 */
export const AvatarToggleButton = ({ isActive, isBusy, onStart, onStop, className }: Props) => {
    const { t } = useTranslation();

    const label = isActive ? t("avatar.stop") : t("avatar.start");
    const classes = [styles.launcher, isActive ? styles.launcherActive : "", className].filter(Boolean).join(" ");

    return (
        <Tooltip content={label} relationship="label">
            <button
                type="button"
                className={classes}
                disabled={isBusy}
                aria-label={label}
                aria-pressed={isActive}
                onClick={isActive ? onStop : onStart}
            >
                {isActive ? (
                    <VideoPersonOff24Filled className={styles.icon} />
                ) : (
                    <VideoPersonSparkle24Filled className={styles.icon} />
                )}
            </button>
        </Tooltip>
    );
};
