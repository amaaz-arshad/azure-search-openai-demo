import { Button, Tooltip } from "@fluentui/react-components";
import { VideoPersonSparkle28Filled } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

/** Live session: the same red the composer's mic uses while it is recording. */
const LIVE_GLYPH_COLOR = "rgba(250, 0, 0, 0.7)";

interface Props {
    isActive: boolean;
    isBusy: boolean;
    onStart: () => void;
    onStop: () => void;
    /** Glyph colour at rest. Match the composer's other buttons, not the Fluent accent. */
    idleColor?: string;
}

/**
 * Control for the live avatar, shaped as a composer icon button.
 *
 * It lives in the question input's button row, to the right of the mic, so the three voice-adjacent
 * actions (send, dictate, talk to the avatar) sit together where a user looks for them. That is why
 * it is a bare 28px glyph on the default Fluent surface rather than the solid accent-coloured circle
 * it used to be as a floating launcher: inside the composer a 3rem filled circle dwarfs its
 * neighbours and reads as a different class of control.
 *
 * The glyph is `VideoPersonSparkle`: a person in a video frame, plus the sparkle that now
 * universally marks AI. That combination is doing real work — widget guidance is blunt that a
 * persona must not imply a human is present, and the sparkle is what keeps this honest while still
 * promising a face rather than a text box. A live session recolours it red rather than swapping in
 * an "off" glyph, exactly as the mic does while recording: there is no 28px `VideoPersonOff`, and
 * colour is how this composer already signals "running, tap to end".
 *
 * Starting is deliberately an explicit user action rather than something that happens on page
 * load: the session bills per minute of wall-clock time, and the bots that use this are ungated
 * and publicly embeddable.
 */
export const AvatarToggleButton = ({ isActive, isBusy, onStart, onStop, idleColor = "black" }: Props) => {
    const { t } = useTranslation();

    const label = isActive ? t("avatar.stop") : t("avatar.start");

    return (
        <Tooltip content={label} relationship="label" showDelay={0} hideDelay={0}>
            <Button
                size="large"
                icon={<VideoPersonSparkle28Filled primaryFill={isActive ? LIVE_GLYPH_COLOR : idleColor} />}
                aria-label={label}
                aria-pressed={isActive}
                disabled={isBusy}
                onClick={isActive ? onStop : onStart}
            />
        </Tooltip>
    );
};
