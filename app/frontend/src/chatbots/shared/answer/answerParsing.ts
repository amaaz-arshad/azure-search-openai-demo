type QueryPlanStepLike = {
    id?: number | string | null;
    type?: string;
    label?: string;
};

type ThoughtLike = {
    props?: {
        query_plan?: QueryPlanStepLike[];
    };
};

type ActivityDetailLike = {
    id?: number | string;
    number?: number;
    type?: string;
    source?: string;
};

type ExternalResultMetadataLike = {
    title?: string;
    url?: string;
};

type ChatAppResponseLike = {
    message: {
        content: string;
    };
    context?: {
        thoughts?: ThoughtLike[];
        followup_questions?: string[] | null;
        data_points?: {
            citations?: string[];
            citation_activity_details?: Record<string, ActivityDetailLike>;
            external_results_metadata?: ExternalResultMetadataLike[];
        };
    };
};

export type CitationDetail = {
    reference: string;
    index: number;
    isWeb: boolean;
    displayLabel?: string;
    activityId?: string;
    stepNumber?: number;
    stepLabel?: string;
    stepSource?: string;
};

type CitationFragment =
    | { type: "text"; value: string }
    | {
          type: "citation";
          detail: CitationDetail;
      };

type ActivityStepMeta = {
    stepNumber: number;
    stepLabel: string;
};

export type ParsedAnswer = {
    markdown: string;
    citations: CitationDetail[];
    citationLinks: Record<string, CitationDetail>;
};

const activityTypeLabels: Record<string, string> = {
    modelQueryPlanning: "Query planning",
    searchIndex: "Index search",
    web: "Web search",
    remoteSharePoint: "SharePoint search",
    agenticReasoning: "Agentic reasoning",
    modelAnswerSynthesis: "Answer synthesis"
};

const citationScheme = "#citation-";

const isWebCitation = (reference: string) => reference.startsWith("http://") || reference.startsWith("https://");

const getStepLabel = (step: QueryPlanStepLike): string => {
    if (step.label?.trim()) {
        return step.label;
    }
    if (step.type && activityTypeLabels[step.type]) {
        return activityTypeLabels[step.type];
    }
    return step.type || "Search step";
};

const normalizeAnswerText = (answer: ChatAppResponseLike, isStreaming: boolean): string => {
    let parsedAnswer = answer.message.content.trim();

    if (isStreaming) {
        let lastIndex = parsedAnswer.length;
        for (let i = parsedAnswer.length - 1; i >= 0; i--) {
            if (parsedAnswer[i] === "]") {
                break;
            } else if (parsedAnswer[i] === "[") {
                lastIndex = i;
                break;
            }
        }
        parsedAnswer = parsedAnswer.substring(0, lastIndex);
    }

    return parsedAnswer;
};

const buildActivityStepMap = (answer: ChatAppResponseLike): Record<string, ActivityStepMeta> => {
    const mapping: Record<string, ActivityStepMeta> = {};
    const thoughts = answer.context?.thoughts;
    if (!Array.isArray(thoughts)) {
        return mapping;
    }

    const thoughtWithPlan = thoughts.find(thought => Array.isArray(thought.props?.query_plan));
    if (!thoughtWithPlan) {
        return mapping;
    }

    const planSteps = thoughtWithPlan.props?.query_plan ?? [];
    planSteps.forEach((step, index) => {
        if (step && step.id !== undefined && step.id !== null) {
            mapping[String(step.id)] = {
                stepNumber: index + 1,
                stepLabel: getStepLabel(step)
            };
        }
    });

    return mapping;
};

const collectCitations = (answer: ChatAppResponseLike, isStreaming: boolean): { fragments: CitationFragment[]; citations: CitationDetail[] } => {
    const possibleCitations = answer.context?.data_points?.citations || [];
    const citationActivityDetails = answer.context?.data_points?.citation_activity_details ?? {};
    const activitySteps = buildActivityStepMap(answer);
    const externalResults = answer.context?.data_points?.external_results_metadata || [];
    const externalResultsByUrl = new Map(externalResults.filter(result => result.url).map(result => [result.url as string, result]));
    const parsedAnswer = normalizeAnswerText(answer, isStreaming);
    const parts = parsedAnswer.split(/\[([^\]]+)\]/g);

    const resolveSharePointUrl = (citation: string): string => {
        if (isWebCitation(citation)) {
            return citation;
        }

        const hasFileExtension = /\.(pdf|docx?|xlsx?|pptx?|txt|html?|csv)$/i.test(citation);
        if (!hasFileExtension) {
            return citation;
        }

        const matchingResult = externalResults.find(result => {
            if (!result.url) {
                return false;
            }
            const urlParts = result.url.split("/");
            const urlFilename = urlParts[urlParts.length - 1];
            return urlFilename === citation || decodeURIComponent(urlFilename) === citation;
        });

        return matchingResult?.url || citation;
    };

    const fragments: CitationFragment[] = [];
    const citationMap = new Map<string, CitationDetail>();
    const citationList: CitationDetail[] = [];

    parts.forEach((part, index) => {
        if (index % 2 === 0) {
            fragments.push({ type: "text", value: part });
            return;
        }

        const isValidCitation = possibleCitations.some(citation => citation.endsWith(part));
        if (!isValidCitation) {
            fragments.push({ type: "text", value: `[${part}]` });
            return;
        }

        const resolvedReference = resolveSharePointUrl(part);
        const existing = citationMap.get(resolvedReference);
        if (existing) {
            fragments.push({ type: "citation", detail: existing });
            return;
        }

        const backendDetail = citationActivityDetails?.[part];
        const activityId = backendDetail?.id;
        const stepMeta = activityId ? activitySteps[String(activityId)] : undefined;
        const externalResult = externalResultsByUrl.get(resolvedReference);
        const activityLabel = backendDetail?.type ? activityTypeLabels[backendDetail.type] || backendDetail.type : undefined;

        const detail: CitationDetail = {
            reference: resolvedReference,
            index: citationList.length + 1,
            isWeb: isWebCitation(resolvedReference),
            displayLabel: externalResult?.title?.trim() || undefined,
            activityId: activityId !== undefined ? String(activityId) : undefined,
            stepNumber: backendDetail?.number ?? stepMeta?.stepNumber,
            stepLabel: activityLabel ?? stepMeta?.stepLabel,
            stepSource: backendDetail?.source
        };

        citationMap.set(resolvedReference, detail);
        citationList.push(detail);
        fragments.push({ type: "citation", detail });
    });

    return { fragments, citations: citationList };
};

export const getCitationHref = (detail: CitationDetail): string => `${citationScheme}${detail.index}`;

export const isCitationHref = (href?: string | null): href is string => !!href && href.startsWith(citationScheme);

export const stripCitationLinks = (markdown: string): string =>
    markdown
        .replace(/\[(\d+)\]\(#citation-\d+\)/g, "")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();

export function parseAnswerToMarkdown(answer: ChatAppResponseLike, isStreaming: boolean): ParsedAnswer {
    const { fragments, citations } = collectCitations(answer, isStreaming);
    const citationLinks: Record<string, CitationDetail> = {};

    const markdown = fragments
        .map(fragment => {
            if (fragment.type === "text") {
                return fragment.value;
            }

            const href = getCitationHref(fragment.detail);
            citationLinks[href] = fragment.detail;
            return `[${fragment.detail.index}](${href})`;
        })
        .join("");

    return {
        markdown,
        citations,
        citationLinks
    };
}
