import { useEffect, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { useLogin, checkLoggedIn } from "./authConfig";
import { LoginContext } from "./loginContext";
import BasicLogin from "./pages/basicauth/BasicLogin";
import { getCurrentSession, PublicTestSession } from "./pages/basicauth/basicAuth";
import Layout from "./pages/layout/Layout";

const LayoutWrapper = () => {
    const [loggedIn, setLoggedIn] = useState<boolean>(false);
    const [basicAuthenticated, setBasicAuthenticated] = useState<boolean>(false);
    const [currentUser, setCurrentUser] = useState<PublicTestSession | null>(null);
    const [isAuthResolved, setIsAuthResolved] = useState(false);

    useEffect(() => {
        let isMounted = true;

        void getCurrentSession({ forceRefresh: true })
            .then(session => {
                if (!isMounted) {
                    return;
                }
                const isAuthenticated = session !== null;
                setCurrentUser(session);
                setBasicAuthenticated(isAuthenticated);
                setLoggedIn(isAuthenticated);
            })
            .catch(error => {
                console.error("Nerilio Bot session check failed", error);
                if (!isMounted) {
                    return;
                }
                setCurrentUser(null);
                setBasicAuthenticated(false);
                setLoggedIn(false);
            })
            .finally(() => {
                if (isMounted) {
                    setIsAuthResolved(true);
                }
            });

        return () => {
            isMounted = false;
        };
    }, []);

    const handleAuthSuccess = (session: PublicTestSession) => {
        setBasicAuthenticated(true);
        setLoggedIn(true);
        setCurrentUser(session);
        setIsAuthResolved(true);
    };

    if (!isAuthResolved) {
        return null;
    }

    if (!basicAuthenticated) {
        return <BasicLogin onSuccess={handleAuthSuccess} />;
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
                <Layout />
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
                <Layout />
            </LoginContext.Provider>
        );
    }
};

export default LayoutWrapper;

