"""Canonical evidence facts for Capital stress/scenario vectors."""

from typing import Dict, List

from app.core import evidence as E
from app.core.evidence_broker import capture_observation


async def capture_scenario_vectors(
    *,
    user_id: str,
    keys: List[str],
    vectors: List[Dict],
) -> Dict:
    """Persist the exact numeric shocks used by a scenario matrix.

    Scenario vectors are SIMULATION facts: they are deliberate hypothetical
    inputs, never observations. Stable built-in vector definitions may reuse a
    fresh canonical fact ID; every receipt still links to the facts it used.
    """
    evidence_ids: List[str] = []
    by_scenario: Dict[str, Dict] = {}

    for key, vector in zip(keys, vectors):
        label = str(vector.get("label") or key)
        scenario_facts: Dict[str, str] = {}
        for metric, raw_value in vector.items():
            if metric == "label" or not isinstance(raw_value, (int, float)):
                continue
            evidence_id = await capture_observation(
                domain="capital",
                metric=f"scenario_{metric}",
                subject_id=key,
                value=float(raw_value),
                unit="pct_shift" if metric.endswith("_pct") else "scenario_value",
                state=E.SIMULATION,
                provider="capital_scenario_engine",
                source_type="simulation",
                methodology="Built-in Capital stress/scenario vector",
                user_id=user_id,
                extra={"scenario_key": key, "scenario_label": label, "vector_metric": metric},
            )
            evidence_ids.append(evidence_id)
            scenario_facts[metric] = evidence_id
        by_scenario[key] = {
            "label": label,
            "facts": scenario_facts,
        }

    return {
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "scenarios": by_scenario,
    }
