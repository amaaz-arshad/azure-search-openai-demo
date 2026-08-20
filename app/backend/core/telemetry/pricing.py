"""Token prices and the cost arithmetic built on them.

**Everything here is EUR**, because that is what this subscription bills: every row the Cost
Management query returns carries ``Currency: "EUR"``. A USD table rendered with a euro sign would
bake an FX-plus-list-markup error of roughly 8-15% into the estimated-vs-actual reconciliation --
the one number that panel exists to check -- so a real 15% pricing mistake would be indistinguishable
from normal drift. Every stored cost therefore carries an explicit currency code, and
`compare_currencies` refuses to mix them.

Prices come from three layers, later winning:

1. ``COMPILED_MODEL_PRICES`` below -- measured from real billed meters, see the provenance note.
2. ``AZURE_OPENAI_PRICE_TABLE`` -- a JSON env var, mirroring `AZURE_OPENAI_CHAT_MODEL_DEPLOYMENTS`.
3. ``telemetry/pricing/prices.json`` -- editable from the Costs tab, no redeploy.

An unknown model yields ``None``, never 0. A silent zero would make an unpriced model look free,
which is the one failure mode a cost dashboard must not have. A model missing from every layer shows
up in the dashboard's "unpriced models" strip, which links to the in-app price editor -- that editor
is the only way a new model gets a price, now that billed meters are no longer read.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from core.telemetry.records import TokenCounts

logger = logging.getLogger("telemetry")

CURRENCY_EUR = "EUR"

# Bumped whenever the compiled table changes. Stamped onto every stored row, so re-pricing history is
# a deliberate act rather than a side effect of a deploy.
PRICE_VERSION = "20260819"

# Cost is stored as an integer number of millionths of a currency unit, so no float ever round-trips
# through a string and totals over hundreds of thousands of rows stay exact.
MICROS_PER_UNIT = 1_000_000
TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """Currency units per 1,000,000 tokens."""

    input: float
    cached_input: float
    output: float
    currency: str = CURRENCY_EUR
    source: str = "compiled"

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "cachedInput": self.cached_input,
            "output": self.output,
            "currency": self.currency,
            "source": self.source,
        }


# Provenance: measured on 2026-08-19 from the Azure Cost Management meters actually billed by
# `cog-bfmtryd6z3arm` over 2026-08-01..18, as `cost / (quantity * unitTokens)` per role. Meters whose
# name ends `1M Tokens` bill per 1,000,000 tokens; the ones ending plain `Tokens` bill per 1,000 --
# missing that distinction is a 1000x error, so it is asserted in the tests.
#
# Models the account has never billed are deliberately ABSENT rather than guessed: the dashboard
# reports them as unpriced and points at the price editor, which is honest, where a made-up number
# would not be.
COMPILED_MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.4-mini": ModelPrice(input=1.3179, cached_input=0.1318, output=7.9077),
    "gpt-4.1": ModelPrice(input=3.0753, cached_input=0.7694, output=12.3018),
    "gpt-4.1-mini": ModelPrice(input=0.3514, cached_input=0.0880, output=1.4022),
    "gpt-5": ModelPrice(input=1.1053, cached_input=0.1097, output=9.1083),
    "text-embedding-3-large": ModelPrice(input=0.1142, cached_input=0.1142, output=0.0),
}


def normalize_model_name(model: Any) -> Optional[str]:
    if not isinstance(model, str):
        return None
    normalized = model.strip().lower()
    return normalized or None


def parse_price_mapping(payload: Any, *, source: str) -> dict[str, ModelPrice]:
    """Read a ``{model: {input, cachedInput, output}}`` mapping, skipping anything malformed.

    Tolerant on purpose: this parses an env var and an operator-edited blob, and one bad entry must
    not cost us the whole table.
    """
    if not isinstance(payload, dict):
        return {}

    prices: dict[str, ModelPrice] = {}
    for raw_model, raw_price in payload.items():
        model = normalize_model_name(raw_model)
        if model is None or not isinstance(raw_price, dict):
            continue

        def read(*names: str) -> Optional[float]:
            for name in names:
                value = raw_price.get(name)
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)) and value >= 0:
                    return float(value)
            return None

        price_input = read("input", "inputPerMillion", "input_per_million")
        price_output = read("output", "outputPerMillion", "output_per_million")
        if price_input is None or price_output is None:
            logger.warning("Skipping malformed price entry for %s from %s", model, source)
            continue
        price_cached = read("cachedInput", "cached_input", "cached")
        currency = raw_price.get("currency")
        prices[model] = ModelPrice(
            input=price_input,
            cached_input=price_input if price_cached is None else price_cached,
            output=price_output,
            currency=currency if isinstance(currency, str) and currency else CURRENCY_EUR,
            source=source,
        )
    return prices


def load_env_price_table() -> dict[str, ModelPrice]:
    raw = os.getenv("AZURE_OPENAI_PRICE_TABLE", "").strip()
    if not raw:
        return {}
    try:
        return parse_price_mapping(json.loads(raw), source="env")
    except json.JSONDecodeError:
        logger.warning("AZURE_OPENAI_PRICE_TABLE is not valid JSON; ignoring it")
        return {}


@dataclass(frozen=True)
class CostEstimate:
    """`micros` is None when the model has no price at any layer -- distinct from a genuine zero."""

    micros: Optional[int]
    currency: str
    price_version: str
    model: Optional[str]

    @property
    def is_priced(self) -> bool:
        return self.micros is not None


class PriceTable:
    """The merged, layered price table. Cheap to construct; held on the telemetry store and refreshed
    when the Azure cost cache is refreshed."""

    def __init__(
        self,
        *,
        compiled: Optional[dict[str, ModelPrice]] = None,
        env: Optional[dict[str, ModelPrice]] = None,
        override: Optional[dict[str, ModelPrice]] = None,
        version: str = PRICE_VERSION,
    ):
        self.compiled = dict(COMPILED_MODEL_PRICES if compiled is None else compiled)
        self.env = dict(env if env is not None else load_env_price_table())
        self.override = dict(override or {})
        self.version = version

    def merged(self) -> dict[str, ModelPrice]:
        merged: dict[str, ModelPrice] = {}
        for layer in (self.compiled, self.env, self.override):
            merged.update(layer)
        return merged

    def price_for(self, model: Any) -> Optional[ModelPrice]:
        normalized = normalize_model_name(model)
        if normalized is None:
            return None
        for layer in (self.override, self.env, self.compiled):
            price = layer.get(normalized)
            if price is not None:
                return price
        return None

    def estimate(self, model: Any, usage: TokenCounts) -> CostEstimate:
        """cost = (prompt - cached) * input + cached * cached_input + completion * output

        `completion` already contains `reasoning` and `prompt` already contains `cached`, so neither
        is added on top -- they are breakdowns. Adding reasoning would roughly double the cost of
        every reasoning-model turn.
        """
        normalized = normalize_model_name(model)
        price = self.price_for(normalized)
        if price is None:
            return CostEstimate(micros=None, currency=CURRENCY_EUR, price_version=self.version, model=normalized)

        uncached_prompt = max(0, usage.prompt - usage.cached)
        units = (
            uncached_prompt * price.input + usage.cached * price.cached_input + usage.completion * price.output
        )
        micros = int(round(units * MICROS_PER_UNIT / TOKENS_PER_MILLION))
        return CostEstimate(
            micros=micros, currency=price.currency, price_version=self.version, model=normalized
        )

    def as_payload(self) -> dict[str, Any]:
        merged = self.merged()
        return {
            "version": self.version,
            "currency": CURRENCY_EUR,
            "prices": {model: price.as_dict() for model, price in sorted(merged.items())},
        }


def compare_currencies(left: Optional[str], right: Optional[str]) -> bool:
    """True only when two amounts are safe to add or divide. A missing code is not a match: an
    unlabelled amount is exactly the case this guard exists to catch."""
    if not left or not right:
        return False
    return left.strip().upper() == right.strip().upper()


def micros_to_units(micros: Optional[int]) -> Optional[float]:
    """For display only. Never round-trip a stored cost through this."""
    if micros is None:
        return None
    return micros / MICROS_PER_UNIT
