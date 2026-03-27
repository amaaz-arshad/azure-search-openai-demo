import { useEffect, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { useLogin, checkLoggedIn } from "./authConfig";
import { LoginContext } from "./loginContext";
import BasicLogin from "./pages/basicauth/BasicLogin";
import { getAuthenticatedUser, isAuthenticated, RakUser } from "./pages/basicauth/basicAuth";
import Layout from "./pages/layout/Layout";
import { ChatbotThemeRoot } from "../shared/theme/ChatbotThemeRoot";

const LayoutWrapper = () => {
    const [loggedIn, setLoggedIn] = useState(false);
    const [basicAuthenticated, setBasicAuthenticated] = useState<boolean>(isAuthenticated());
    const [currentUser, setCurrentUser] = useState<RakUser | null>(getAuthenticatedUser());

    if (!basicAuthenticated) {
        return (
            <ChatbotThemeRoot chatbotName="rak">
                <BasicLogin
                    onSuccess={() => {
                        setCurrentUser(getAuthenticatedUser());
                        setBasicAuthenticated(true);
                    }}
                />
            </ChatbotThemeRoot>
        );
    }

    if (useLogin) {
        const { instance } = useMsal();
        // Keep track of the mounted state to avoid setting state in an unmounted component
        const mounted = useRef<boolean>(true);
        useEffect(() => {
            mounted.current = true;
            checkLoggedIn(instance)
                .then(isLoggedIn => {
                    if (mounted.current) setLoggedIn(isLoggedIn);
                })
                .catch(e => {
                    console.error("checkLoggedIn failed", e);
                });
            return () => {
                mounted.current = false;
            };
        }, [instance]);

        return (
            <LoginContext.Provider value={{ loggedIn, setLoggedIn, currentUser, setCurrentUser }}>
                <ChatbotThemeRoot chatbotName="rak">
                    <Layout />
                </ChatbotThemeRoot>
            </LoginContext.Provider>
        );
    } else {
        return (
            <LoginContext.Provider
                value={{
                    loggedIn,
                    setLoggedIn,
                    currentUser,
                    setCurrentUser
                }}
            >
                <ChatbotThemeRoot chatbotName="rak">
                    <Layout />
                </ChatbotThemeRoot>
            </LoginContext.Provider>
        );
    }
};

export default LayoutWrapper;
