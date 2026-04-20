import styles from "./UserMessage.module.css";

interface Props {
    message: string;
}

export const UserMessage = ({ message }: Props) => (
    <div className={styles.container}>
        <div className={styles.bubble}>{message}</div>
    </div>
);
