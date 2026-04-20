import { Component as SharedNoPage } from "../../shared/noPage/NoPage";

import { InternalV2BasicAuthGate } from "../basicAuthGate";

export function Component(): JSX.Element {
    return (
        <InternalV2BasicAuthGate>
            <SharedNoPage />
        </InternalV2BasicAuthGate>
    );
}

Component.displayName = "InternalV2NoPage";
