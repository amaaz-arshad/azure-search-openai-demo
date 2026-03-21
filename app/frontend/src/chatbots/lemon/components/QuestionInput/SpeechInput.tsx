import styles from "./QuestionInput.module.css";
import { supportedLngs } from "../../i18n/config";
import { SpeechInputButton } from "../../../shared/speech/SpeechInputButton";

interface Props {
    updateQuestion: (question: string) => void;
}

export const SpeechInput = ({ updateQuestion }: Props) => {
    return (
        <SpeechInputButton
            updateQuestion={updateQuestion}
            supportedLngs={supportedLngs}
            containerClassName={styles.questionInputButtonsContainer}
            idleMicColor="black"
        />
    );
};
