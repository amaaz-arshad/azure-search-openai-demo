import { useEffect, useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { chatbotDefinitions } from "../chatbots/registry";

const DIRECTORY_PASSWORD = (import.meta.env.VITE_CHATBOT_DIRECTORY_PASSWORD as string | undefined) || "chatbot123";

const ChatbotDirectory = () => {
    const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);

    const sortedChatbots = useMemo(() => [...chatbotDefinitions].sort((a, b) => a.name.localeCompare(b.name)), []);

    useEffect(() => {
        const enteredPassword = window.prompt("Enter password to access chatbot directory:");
        if (enteredPassword === DIRECTORY_PASSWORD) {
            setIsAuthenticated(true);
            return;
        }
        window.alert("Incorrect password.");
        setIsAuthenticated(false);
    }, []);

    if (isAuthenticated === null) {
        return null;
    }

    if (!isAuthenticated) {
        return <Navigate to="/" replace />;
    }

    return (
        <main
            style={{
                minHeight: "100vh",
                padding: "24px",
                maxWidth: "700px",
                margin: "0 auto"
            }}
        >
            <h1>Available chatbots</h1>
            <ul>
                {sortedChatbots.map(chatbot => (
                    <li key={chatbot.name}>
                        <Link to={`/${chatbot.name}`}>{chatbot.name}</Link>
                    </li>
                ))}
            </ul>
        </main>
    );
};

export default ChatbotDirectory;
