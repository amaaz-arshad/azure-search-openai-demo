import { useNavigate } from "react-router-dom";
import styles from "./Landing.module.css";

const Landing = () => {
    const navigate = useNavigate();

    return (
        <div className={styles.container}>
            <button className={styles.startButton} onClick={() => navigate("/chat")}>
                Start Chat
            </button>
        </div>
    );
};

export default Landing;
