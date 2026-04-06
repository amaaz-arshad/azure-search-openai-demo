import { useMsal } from "@azure/msal-react";
import { useEffect, useState } from "react";

import { ChatAppResponse, getHeaders } from "../../api";
import { getToken, useLogin } from "../../authConfig";
import { MarkdownViewer } from "../MarkdownViewer";
import styles from "./AnalysisPanel.module.css";
import { AnalysisPanelTabs } from "./AnalysisPanelTabs";

interface Props {
    className: string;
    activeTab: AnalysisPanelTabs;
    onActiveTabChanged: (tab: AnalysisPanelTabs) => void;
    activeCitation: string | undefined;
    citationHeight: string;
    answer: ChatAppResponse;
    onCitationClicked?: (citationFilePath: string) => void;
}

export const AnalysisPanel = ({ activeCitation, citationHeight, className }: Props) => {
    const [citation, setCitation] = useState("");

    const client = useLogin ? useMsal().instance : undefined;

    useEffect(() => {
        let citationObjectUrl: string | null = null;
        let isCancelled = false;

        const fetchCitation = async () => {
            if (!activeCitation) {
                setCitation("");
                return;
            }

            setCitation("");

            const token = client ? await getToken(client) : undefined;
            // Get hash from the URL as it may contain #page=N
            // which helps browser PDF renderer jump to correct page N
            const hashIndex = activeCitation.indexOf("#");
            const originalHash = hashIndex >= 0 ? activeCitation.slice(hashIndex + 1) : "";
            const response = await fetch(activeCitation, {
                method: "GET",
                headers: await getHeaders(token)
            });
            const citationContent = await response.blob();
            citationObjectUrl = URL.createObjectURL(citationContent);
            const nextCitation = originalHash ? `${citationObjectUrl}#${originalHash}` : citationObjectUrl;

            if (!isCancelled) {
                setCitation(nextCitation);
            }
        };

        fetchCitation();

        return () => {
            isCancelled = true;
            if (citationObjectUrl) {
                URL.revokeObjectURL(citationObjectUrl);
            }
        };
    }, [activeCitation, client]);

    const renderFileViewer = () => {
        if (!activeCitation) {
            return null;
        }

        const fileExtension = activeCitation.split("#")[0].split(".").pop()?.toLowerCase();
        switch (fileExtension) {
            case "png":
                return (
                    <div className={styles.citationContent}>
                        <img src={citation || activeCitation} className={styles.citationImg} alt="Citation Image" />
                    </div>
                );
            case "md":
                return (
                    <div className={styles.citationContent}>
                        <MarkdownViewer src={citation || activeCitation} />
                    </div>
                );
            default:
                return (
                    <div className={styles.citationContent}>
                        <iframe title="Citation" src={citation || activeCitation} className={styles.citationFrame} width="100%" height={citationHeight} />
                    </div>
                );
        }
    };

    const panelClassName = [styles.analysisPanel, className].filter(Boolean).join(" ");

    return <div className={panelClassName}>{renderFileViewer()}</div>;
};
