"""Persist classified rework signals into the metrics store."""

from __future__ import annotations

from .metrics_store import MetricsStore, ReworkMetric
from .rework_classifier import ReworkSignal


class ReworkCounter:
    def __init__(self, metrics_store: MetricsStore) -> None:
        self.metrics_store = metrics_store

    def record(self, signal: ReworkSignal) -> None:
        self.metrics_store.record_rework(
            ReworkMetric(
                event_id=signal.event_id,
                issue_id=signal.issue_id,
                issue_identifier=signal.issue_identifier,
                author_id=signal.author_id,
                author_email=signal.author_email,
                from_state=signal.from_state,
                to_state=signal.to_state,
                occurred_at=signal.occurred_at,
            )
        )
