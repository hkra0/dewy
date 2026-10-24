"""Shared measurement semantics; transport/status fields are snapshot metadata."""
SNAPSHOT_METADATA = frozenset({
    "data_version", "water_temp_valid", "water_temp_age", "feeding_state",
    "next_prompt_date", "alarms", "time_valid", "fed_time", "received_at", "stale",
})
METRIC_METADATA = {
    "fed": {"aggregation": "latest"},
    "skipped": {"aggregation": "latest"},
    "feeding_score": {"aggregation": "latest"},
    **{key: {"aggregation": "latest"} for key in SNAPSHOT_METADATA},
}


def aggregation_mode(key, metadata=None):
    return (metadata or {}).get(key, METRIC_METADATA.get(key, {})).get("aggregation", "continuous")
