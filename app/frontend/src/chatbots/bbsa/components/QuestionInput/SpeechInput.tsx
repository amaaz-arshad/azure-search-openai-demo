import styles from "./QuestionInput.module.css";
import { supportedLngs } from "../../i18n/config";
import { SpeechInputButton } from "../../../shared/speech/SpeechInputButton";

interface Props {
    updateQuestion: (question: string) => void;
}

export const SpeechInput = ({ updateQuestion }: Props) => {
    // idleMicColor matches lemon's composer: its send glyph is black on the default Fluent button
    // surface, so the mic has to be black too or it renders in the Fluent accent blue beside it.
    return (
        <SpeechInputButton
            updateQuestion={updateQuestion}
            supportedLngs={supportedLngs}
            containerClassName={styles.questionInputButtonsContainer}
            idleMicColor="black"
        />
    );
};
