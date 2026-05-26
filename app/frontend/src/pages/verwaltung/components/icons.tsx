import { SVGProps } from "react";

/*
 * Inline SVG icons copied verbatim from the nerilio backend source views.
 * Keeping the icons faithful (stroke weights, viewBoxes, points) so the design ports cleanly.
 */

const stroke = (props: SVGProps<SVGSVGElement>): SVGProps<SVGSVGElement> => ({
    fill: "none",
    stroke: "currentColor",
    ...props
});

export const CloseIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2.5} {...stroke(props)}>
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
);

export const PlusIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2.5} {...stroke(props)}>
        <line x1="12" y1="5" x2="12" y2="19" />
        <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
);

export const EditIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
);

export const DeleteIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6l-1 14H6L5 6" />
        <path d="M10 11v6" />
        <path d="M14 11v6" />
        <path d="M9 6V4h6v2" />
    </svg>
);

export const ViewIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
        <circle cx="12" cy="12" r="3" />
    </svg>
);

export const ChevronLeftIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polyline points="15 18 9 12 15 6" />
    </svg>
);

export const ChevronDownIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polyline points="6 9 12 15 18 9" />
    </svg>
);

export const ChevronUpIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="14" height="14" viewBox="0 0 24 24" strokeWidth={2.5} {...stroke(props)}>
        <polyline points="18 15 12 9 6 15" />
    </svg>
);

export const StopSquareIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" {...props}>
        <rect x="6" y="6" width="12" height="12" />
    </svg>
);

export const PlayTriangleIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" {...props}>
        <polygon points="5,3 19,12 5,21" />
    </svg>
);

export const PlayTriangleSmallIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="13" height="13" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
);

export const DeleteSmallIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="13" height="13" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6l-1 14H6L5 6" />
        <path d="M10 11v6" />
        <path d="M14 11v6" />
        <path d="M9 6V4h6v2" />
    </svg>
);

export const EditSmallIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="13" height="13" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
);

export const FileIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
        <polyline points="13 2 13 9 20 9" />
    </svg>
);

export const FileDelIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="14" height="14" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6l-1 14H6L5 6" />
        <path d="M9 6V4h6v2" />
    </svg>
);

export const KbIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
);

export const UploadCloudIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="28" height="28" viewBox="0 0 24 24" strokeWidth={1.5} {...stroke(props)}>
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
);

export const TextLinesIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="14" height="14" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="15" y2="18" />
    </svg>
);

export const OpenExternalIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="13" height="13" viewBox="0 0 24 24" strokeWidth={2.5} {...stroke(props)}>
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
);

export const RobotIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="22" height="22" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <rect x="3" y="3" width="18" height="14" rx="3" />
        <path d="M8 21h8" />
        <path d="M12 17v4" />
    </svg>
);

/* ============================================================
   Configure-page section icons (one per accordion section).
   Copied verbatim from configure.php.
   ============================================================ */

export const SectionGeneralIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.07 4.93A10 10 0 1 0 4.93 19.07 10 10 0 0 0 19.07 4.93z" />
    </svg>
);

export const SectionLanguagesIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M2 12h20M2 12a10 10 0 0 0 10 10M2 12a10 10 0 0 1 10-10M22 12a10 10 0 0 1-10 10M22 12a10 10 0 0 0-10-10M12 2c-2.8 3-4 6-4 10s1.2 7 4 10M12 2c2.8 3 4 6 4 10s-1.2 7-4 10" />
    </svg>
);

export const SectionLlmIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <path d="M8 21h8M12 17v4" />
        <path d="M7 8h2m2 0h2m2 0h2M7 11h2m4 0h2" />
    </svg>
);

export const SectionPromptIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <polyline points="4 17 10 11 4 5" />
        <line x1="12" y1="19" x2="20" y2="19" />
    </svg>
);

export const SectionModesIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
    </svg>
);

export const SectionDesignIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <circle cx="13.5" cy="6.5" r="2.5" />
        <circle cx="17.5" cy="10.5" r="2.5" />
        <circle cx="8.5" cy="7.5" r="2.5" />
        <circle cx="6.5" cy="12.5" r="2.5" />
        <path d="M12 20a7 7 0 1 1 0-14 7 7 0 0 1 0 14z" strokeDasharray="4 2" />
    </svg>
);

export const SectionGreetingIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
);

export const SectionDisclaimerIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
);

export const SectionFeaturesIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
);

export const SectionLoginIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <rect x="3" y="11" width="18" height="11" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
);

export const SectionQaBehaviorIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
);

export const SectionTutorLevelIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M2 20h20M6 20V10l6-6 6 6v10" />
        <path d="M10 20v-5h4v5" />
    </svg>
);

export const SectionTutorMethodIcon = (props: SVGProps<SVGSVGElement>) => EditIcon(props);

export const SectionAssessFormatIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth={2} {...stroke(props)}>
        <path d="M9 11l3 3L22 4" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
);

export const PillCloseIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="10" height="10" viewBox="0 0 24 24" strokeWidth={3} {...stroke(props)}>
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
);

export const PlusTinyIcon = (props: SVGProps<SVGSVGElement>) => (
    <svg width="11" height="11" viewBox="0 0 24 24" strokeWidth={3} {...stroke(props)}>
        <line x1="12" y1="5" x2="12" y2="19" />
        <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
);

export const ToggleAllIcon = (props: SVGProps<SVGSVGElement> & { expanded?: boolean }) => {
    const { expanded, ...rest } = props;
    return (
        <svg width="14" height="14" viewBox="0 0 24 24" strokeWidth={2.5} {...stroke(rest)}>
            <polyline points={expanded ? "18 15 12 9 6 15" : "6 9 12 15 18 9"} />
        </svg>
    );
};
