import type { PropsWithChildren } from "react";
import { useState } from "react";

import BasicLogin from "./pages/basicauth/BasicLogin";
import { isAuthenticated } from "./pages/basicauth/basicAuth";

export const InternalBasicAuthGate = ({ children }: PropsWithChildren) => {
    const [basicAuthenticated, setBasicAuthenticated] = useState<boolean>(isAuthenticated());

    if (!basicAuthenticated) {
        return <BasicLogin onSuccess={() => setBasicAuthenticated(true)} />;
    }

    return <>{children}</>;
};
