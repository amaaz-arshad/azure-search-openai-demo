import type { ReactElement } from "react";
import { Tooltip } from "@fluentui/react-components";

interface TooltipTargetProps {
    /** Tooltip text. Rendered in the shared `.fui-Tooltip__content` dark pill. */
    label: string;
    /** Optional class for the wrapper span (e.g. to carry layout such as a float). */
    className?: string;
    /** A single control to annotate — typically a Fluent v8 IconButton. */
    children: ReactElement;
}

/**
 * Wraps a control in a Fluent v9 Tooltip so it inherits the global
 * `.fui-Tooltip__content` dark-pill styling, replacing the unstyled native
 * `title` tooltip.
 *
 * Fluent v9 Tooltip anchors by injecting a DOM ref into its single child, but
 * Fluent v8 components (IconButton) forward `ref` to their class instance, not
 * a DOM node, so a Tooltip cannot position against them directly. The host
 * <span> gives the Tooltip a real element to anchor to; hovering the inner
 * control still fires the span's pointer handlers. The control keeps its own
 * `ariaLabel`, so dropping the native `title` does not affect accessibility.
 */
export const TooltipTarget = ({ label, className, children }: TooltipTargetProps) => (
    <Tooltip content={label} relationship="label" showDelay={0} hideDelay={0}>
        <span className={className} style={{ display: "inline-flex" }}>
            {children}
        </span>
    </Tooltip>
);
