import { Component as SharedNoPage } from "../../shared/noPage/NoPage";

import { InternalBasicAuthGate } from "../basicAuthGate";

export function Component(): JSX.Element {
    return (
        <InternalBasicAuthGate>
            <SharedNoPage />
        </InternalBasicAuthGate>
    );
}

Component.displayName = "InternalNoPage";
