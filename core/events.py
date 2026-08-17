"""
Système d'événements pour l'observabilité temps réel.
Chaque action de l'agent génère un événement structuré visible dans l'UI.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable


# Types d'événements disponibles
RESEARCH_STARTED          = "research_started"
PLAN_CREATED              = "plan_created"
PHASE_CHANGED             = "phase_changed"
SEARCH_STARTED            = "search_started"
SEARCH_COMPLETED          = "search_completed"
PAGE_OPENED               = "page_opened"
BROWSER_STARTED           = "browser_started"
DOCUMENT_FOUND            = "document_found"
PDF_PROCESSED             = "pdf_processed"
EVIDENCE_EXTRACTED        = "evidence_extracted"
ENTITY_DISCOVERED         = "entity_discovered"
ENTITY_RESOLVED           = "entity_resolved"
ENTITY_REJECTED           = "entity_rejected"
ENTITY_DUPLICATE          = "entity_duplicate"
VERIFICATION_COMPLETED    = "verification_completed"
CONTRADICTION_FOUND       = "contradiction_found"
COVERAGE_UPDATED          = "coverage_updated"
RECOVERY_STARTED          = "recovery_started"
ANALYSIS_STARTED          = "analysis_started"
REPORT_GENERATED          = "report_generated"
RESEARCH_COMPLETED        = "research_completed"
RESEARCH_FAILED           = "research_failed"
QUERY_PLANNED             = "query_planned"
INFORMATION_GAIN          = "information_gain"
BUDGET_WARNING            = "budget_warning"
PROVIDER_FAILED           = "provider_failed"
PROVIDER_FALLBACK         = "provider_fallback"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchEvent:
    """Événement structuré d'observabilité."""

    def __init__(
        self,
        event_type: str,
        message: str,
        study_id: str = "",
        run_id: str = "",
        data: dict[str, Any] | None = None,
        phase: str = "",
    ):
        self.event_type = event_type
        self.message    = message
        self.study_id   = study_id
        self.run_id     = run_id
        self.data       = data or {}
        self.phase      = phase
        self.timestamp  = _now()

    def to_dict(self) -> dict:
        return {
            "timestamp":  self.timestamp,
            "type":       self.event_type,
            "message":    self.message,
            "phase":      self.phase,
            "study_id":   self.study_id,
            "run_id":     self.run_id,
            "data":       self.data,
        }

    def to_log_line(self) -> str:
        ts = self.timestamp[11:19]  # HH:MM:SS
        data_str = ""
        if self.data:
            parts = []
            for k, v in list(self.data.items())[:3]:
                parts.append(f"{k}={v}")
            data_str = " | " + ", ".join(parts)
        return f"[{ts}] {self.message}{data_str}"


class EventBus:
    """
    Bus d'événements léger pour diffuser les updates en temps réel.
    Supporte plusieurs abonnés (Streamlit, WebSocket, logs…).
    """

    def __init__(self):
        self._subscribers: list[Callable[[ResearchEvent], None]] = []
        self._async_subscribers: list[Callable[[ResearchEvent], Any]] = []
        self._history: list[ResearchEvent] = []
        self._max_history = 500

    def subscribe(self, callback: Callable[[ResearchEvent], None]) -> None:
        """Abonner une fonction synchrone."""
        self._subscribers.append(callback)

    def subscribe_async(self, callback: Callable[[ResearchEvent], Any]) -> None:
        """Abonner une coroutine async."""
        self._async_subscribers.append(callback)

    def publish(self, event: ResearchEvent) -> None:
        """Publier synchrone (depuis code sync)."""
        if len(self._history) >= self._max_history:
            self._history.pop(0)
        self._history.append(event)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception:
                pass

    async def apublish(self, event: ResearchEvent) -> None:
        """Publier async (depuis code async)."""
        if len(self._history) >= self._max_history:
            self._history.pop(0)
        self._history.append(event)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception:
                pass
        for sub in self._async_subscribers:
            try:
                await sub(event)
            except Exception:
                pass

    def get_history(self, study_id: str = "", last_n: int = 100) -> list[dict]:
        events = self._history
        if study_id:
            events = [e for e in events if e.study_id == study_id]
        return [e.to_dict() for e in events[-last_n:]]

    def clear(self, study_id: str = "") -> None:
        if study_id:
            self._history = [e for e in self._history if e.study_id != study_id]
        else:
            self._history.clear()


# Singleton global du bus d'événements
event_bus = EventBus()


# ---------------------------------------------------------------------------
# Helper functions pour simplifier la publication d'événements
# ---------------------------------------------------------------------------

async def emit(
    event_type: str,
    message: str,
    study_id: str = "",
    run_id: str = "",
    phase: str = "",
    **data_kwargs,
) -> None:
    """Émettre un événement de manière async."""
    event = ResearchEvent(
        event_type=event_type,
        message=message,
        study_id=study_id,
        run_id=run_id,
        data=data_kwargs,
        phase=phase,
    )
    await event_bus.apublish(event)


def emit_sync(
    event_type: str,
    message: str,
    study_id: str = "",
    run_id: str = "",
    phase: str = "",
    **data_kwargs,
) -> None:
    """Émettre un événement de manière synchrone."""
    event = ResearchEvent(
        event_type=event_type,
        message=message,
        study_id=study_id,
        run_id=run_id,
        data=data_kwargs,
        phase=phase,
    )
    event_bus.publish(event)
