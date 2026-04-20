import { useEffect, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { useLogin, checkLoggedIn } from "./authConfig";
import { InternalV2BasicAuthGate } from "./basicAuthGate";
import { LoginContext } from "./loginContext";
import Layout from "./pages/layout/Layout";

const InternalV2Layout = () => {
    const [loggedIn, setLoggedIn] = useState(false);
    if (useLogin) {
        const { instance } = useMsal();
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
            <LoginContext.Provider value={{ loggedIn, setLoggedIn }}>
                <Layout />
            </LoginContext.Provider>
        );
    } else {
        return (
            <LoginContext.Provider value={{ loggedIn, setLoggedIn }}>
                <Layout />
            </LoginContext.Provider>
        );
    }
};

const LayoutWrapper = () => {
    return (
        <InternalV2BasicAuthGate>
            <InternalV2Layout />
        </InternalV2BasicAuthGate>
    );
};

export default LayoutWrapper;
