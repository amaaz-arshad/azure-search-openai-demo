"""Reading the agentic-retrieval activity records into telemetry steps.

This closes the platform's biggest measurement blind spot. `knowledgebase_client.retrieve(...,
include_activity=True)` returns a list of activity records that carry `elapsed_ms`, and for the
query-planning and answer-synthesis records also `input_tokens` and `output_tokens`. Today those land
as raw dicts in a `ThoughtStep`'s `query_plan` prop and are never summed, and `ActivityDetail` drops
them entirely -- so an agentic turn reports **zero** LLM tokens and therefore zero cost, no matter how
much the search service actually spent on its behalf.

Two deliberate choices here:

**Everything is read defensively.** `azure-search-documents` is pinned at a beta (11.7.0b2), and the
activity records are generated models whose field names could be renamed in a later beta. A rename
must degrade to "no tokens recorded", never to an exception on the chat path -- so the SDK is not
imported at all and every field is read through `getattr`/`as_dict`, by several plausible names.

**Tokens belong to the knowledge-base model, not the chat model.** The planning and synthesis calls
run on `AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT` (gpt-4.1-mini here), which is priced completely
differently from the chat model that writes the final answer. Attributing them to the chat model
would overstate agentic cost several-fold.
"""

import logging
from typing import Any, Optional

from core.telemetry import records as rec

logger = logging.getLogger("telemetry")

# The record types the service emits, mapped to the step names the dashboard groups by. Matched on a
# normalized substring rather than an exact class name, because the wire `type` values and the
# generated class names have differed between previews.
ACTIVITY_STEP_NAMES: tuple[tuple[str, str, str], ...] = (
    ("querlplanning", rec.STEP_AGENTIC_QUERY_PLANNING, rec.STEP_TYPE_LLM),
    ("queryplanning", rec.STEP_AGENTIC_QUERY_PLANNING, rec.STEP_TYPE_LLM),
    ("modelqueryplanning", rec.STEP_AGENTIC_QUERY_PLANNING, rec.STEP_TYPE_LLM),
    ("answersynthesis", rec.STEP_AGENTIC_ANSWER_SYNTHESIS, rec.STEP_TYPE_LLM),
    ("modelanswersynthesis", rec.STEP_AGENTIC_ANSWER_SYNTHESIS, rec.STEP_TYPE_LLM),
    ("semanticreranker", rec.STEP_AGENTIC_SEARCH, rec.STEP_TYPE_INDEX),
    ("searchindex", rec.STEP_AGENTIC_SEARCH, rec.STEP_TYPE_INDEX),
    ("web", rec.STEP_AGENTIC_SEARCH, rec.STEP_TYPE_INDEX),
    ("sharepoint", rec.STEP_AGENTIC_SEARCH, rec.STEP_TYPE_INDEX),
)


def normalize_type(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def classify_activity(activity: Any) -> tuple[str, str]:
    """(step name, step type) for one activity record.

    Falls back to a generic search step rather than dropping the record: an unrecognised activity
    still consumed wall-clock time that belongs on the timeline.
    """
    candidates = [normalize_type(getattr(activity, "type", None)), normalize_type(type(activity).__name__)]
    for haystack in candidates:
        if not haystack:
            continue
        for needle, step_name, step_type in ACTIVITY_STEP_NAMES:
            if needle in haystack:
                return step_name, step_type
    return rec.STEP_AGENTIC_SEARCH, rec.STEP_TYPE_INDEX


def read_field(activity: Any, mapping: dict[str, Any], *names: str) -> Optional[int]:
    """Try each name on the object and on its `as_dict()` form, in both snake and camel case."""
    for name in names:
        value = getattr(activity, name, None)
        if isinstance(value, bool):
            value = None
        if isinstance(value, (int, float)):
            return int(value)
        camel = "".join(
            part.capitalize() if index else part for index, part in enumerate(name.split("_"))
        )
        for key in (name, camel):
            candidate = mapping.get(key)
            if isinstance(candidate, bool):
                continue
            if isinstance(candidate, (int, float)):
                return int(candidate)
    return None


def activity_as_dict(activity: Any) -> dict[str, Any]:
    try:
        value = activity.as_dict()
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def read_activity(activity: Any) -> dict[str, Any]:
    mapping = activity_as_dict(activity)
    step_name, step_type = classify_activity(activity)
    return {
        "name": step_name,
        "type": step_type,
        "elapsedMs": read_field(activity, mapping, "elapsed_ms") or 0,
        "inputTokens": read_field(activity, mapping, "input_tokens") or 0,
        "outputTokens": read_field(activity, mapping, "output_tokens") or 0,
        "activityId": read_field(activity, mapping, "id"),
    }


def record_agentic_activity_steps(
    retrieve_step: Any,
    activities: Any,
    *,
    model: Optional[str] = None,
    deployment: Optional[str] = None,
) -> None:
    """Close the parent retrieve step, then add one child step per activity record.

    The parent carries the summed tokens so the drawer can show a single retrieval row, and the
    children carry the breakdown; `roll_up_usage` counts leaves only, so nothing is double counted.
    """
    from core.telemetry import recorder as telemetry

    try:
        parsed = [read_activity(activity) for activity in (activities or [])]
    except Exception:
        logger.exception("Failed to read agentic retrieval activity records")
        parsed = []

    total_input = sum(entry["inputTokens"] for entry in parsed)
    total_output = sum(entry["outputTokens"] for entry in parsed)

    parent = retrieve_step.close(
        usage={"inputTokens": total_input, "outputTokens": total_output},
        model=model,
        deployment=deployment,
        payload={"activityCount": len(parsed)},
    )
    if parent is None:
        return

    offset = parent.start_ms
    for entry in parsed:
        # Any activity that spent tokens is attributed to the knowledge-base model, whether or not we
        # recognised its type. Leaving the model off a token-bearing step would make the pricer fall
        # back to the turn's CHAT model, which is a different (usually far more expensive) price --
        # exactly the wrong answer on the degradation path a future SDK rename would take.
        spent_tokens = entry["inputTokens"] > 0 or entry["outputTokens"] > 0
        attribute_model = entry["type"] == rec.STEP_TYPE_LLM or spent_tokens
        telemetry.add_step(
            entry["name"],
            entry["type"],
            duration_ms=entry["elapsedMs"],
            start_ms=offset,
            usage={"inputTokens": entry["inputTokens"], "outputTokens": entry["outputTokens"]},
            model=model if attribute_model else None,
            deployment=deployment if attribute_model else None,
            parent=parent.index,
            payload={"activityId": entry["activityId"]} if entry["activityId"] is not None else {},
        )
        # The service reports each activity's own elapsed time but not its start, so children are
        # laid out end to end inside the parent. That is the true sequence -- the agent plans, then
        # searches, then synthesizes -- and it keeps the Gantt honest about ordering even though the
        # absolute offsets are reconstructed rather than measured.
        offset += entry["elapsedMs"]
