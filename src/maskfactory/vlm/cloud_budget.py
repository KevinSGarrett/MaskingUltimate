"""Fail-closed, hash-chained daily budget authority for billable cloud teachers."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


class CloudBudgetError(RuntimeError):
    """A cloud request cannot reserve or reconcile spend safely."""


@dataclass(frozen=True)
class BudgetSnapshot:
    local_date: str
    committed_usd: Decimal
    reserved_usd: Decimal
    available_usd: Decimal
    hard_limit_usd: Decimal
    request_count: int


class DailyBudgetLedger:
    """Reserve worst-case cost before a request and reconcile from provider usage afterward."""

    def __init__(
        self,
        path: Path,
        *,
        timezone_name: str,
        hard_limit_usd: Decimal | str | float,
        lock_timeout_sec: float = 5,
        now=lambda: datetime.now(UTC),
    ) -> None:
        self.path = Path(path)
        self.timezone = ZoneInfo(timezone_name)
        self.hard_limit = _money(hard_limit_usd)
        self.lock_timeout_sec = float(lock_timeout_sec)
        self.now = now
        if self.hard_limit <= 0 or self.lock_timeout_sec <= 0:
            raise CloudBudgetError("budget limit and lock timeout must be positive")

    def reserve(
        self,
        *,
        request_id: str,
        provider: str,
        model: str,
        image_id: str,
        label: str,
        maximum_cost_usd: Decimal | str | float,
    ) -> BudgetSnapshot:
        amount = _money(maximum_cost_usd)
        if amount <= 0 or not request_id.strip():
            raise CloudBudgetError("reservation requires a request ID and positive maximum cost")
        with self._lock():
            events = self._read_events()
            if any(event["request_id"] == request_id for event in events):
                raise CloudBudgetError(f"cloud request ID already exists: {request_id}")
            snapshot = self._snapshot(events)
            if snapshot.committed_usd + snapshot.reserved_usd + amount > self.hard_limit:
                raise CloudBudgetError(
                    f"daily cloud hard limit would be exceeded: available={snapshot.available_usd} "
                    f"requested={amount}"
                )
            self._append_event(
                events,
                {
                    "event": "reserved",
                    "request_id": request_id,
                    "provider": provider,
                    "model": model,
                    "image_id": image_id,
                    "label": label,
                    "reserved_usd": str(amount),
                    "actual_usd": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "error": None,
                },
            )
            return self._snapshot((*events, self._last_event()))

    def commit(
        self,
        request_id: str,
        *,
        actual_cost_usd: Decimal | str | float,
        input_tokens: int,
        output_tokens: int,
        error: str | None = None,
    ) -> BudgetSnapshot:
        actual = _money(actual_cost_usd)
        if actual < 0 or input_tokens < 0 or output_tokens < 0:
            raise CloudBudgetError("actual cloud usage cannot be negative")
        with self._lock():
            events = self._read_events()
            reservation = _active_reservation(events, request_id)
            reserved = _money(reservation["reserved_usd"])
            if actual > reserved:
                raise CloudBudgetError(
                    f"provider cost exceeded reserved maximum for {request_id}: {actual}>{reserved}"
                )
            self._append_event(
                events,
                {
                    "event": "committed",
                    "request_id": request_id,
                    "provider": reservation["provider"],
                    "model": reservation["model"],
                    "image_id": reservation["image_id"],
                    "label": reservation["label"],
                    "reserved_usd": reservation["reserved_usd"],
                    "actual_usd": str(actual),
                    "input_tokens": int(input_tokens),
                    "output_tokens": int(output_tokens),
                    "error": str(error)[:500] if error else None,
                },
            )
            return self._snapshot((*events, self._last_event()))

    def release(self, request_id: str, *, error: str) -> BudgetSnapshot:
        with self._lock():
            events = self._read_events()
            reservation = _active_reservation(events, request_id)
            self._append_event(
                events,
                {
                    "event": "released",
                    "request_id": request_id,
                    "provider": reservation["provider"],
                    "model": reservation["model"],
                    "image_id": reservation["image_id"],
                    "label": reservation["label"],
                    "reserved_usd": reservation["reserved_usd"],
                    "actual_usd": "0.000000",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error": str(error)[:500],
                },
            )
            return self._snapshot((*events, self._last_event()))

    def snapshot(self) -> BudgetSnapshot:
        with self._lock():
            return self._snapshot(self._read_events())

    def _snapshot(self, events) -> BudgetSnapshot:
        local_date = self.now().astimezone(self.timezone).date().isoformat()
        states = {}
        for event in events:
            if event["local_date"] == local_date:
                states[event["request_id"]] = event
        committed = sum(
            (
                _money(event["actual_usd"])
                for event in states.values()
                if event["event"] == "committed"
            ),
            Decimal("0"),
        )
        reserved = sum(
            (
                _money(event["reserved_usd"])
                for event in states.values()
                if event["event"] == "reserved"
            ),
            Decimal("0"),
        )
        return BudgetSnapshot(
            local_date,
            committed,
            reserved,
            max(Decimal("0"), self.hard_limit - committed - reserved),
            self.hard_limit,
            len(states),
        )

    def _append_event(self, prior_events, payload: dict) -> None:
        now = self.now().astimezone(UTC)
        previous = prior_events[-1]["sha256"] if prior_events else "0" * 64
        event = {
            "schema_version": "1.0.0",
            "ts": now.isoformat().replace("+00:00", "Z"),
            "local_date": now.astimezone(self.timezone).date().isoformat(),
            **payload,
            "prev_sha256": previous,
        }
        event["sha256"] = _event_hash(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._cached_last = event

    def _last_event(self) -> dict:
        return self._cached_last

    def _read_events(self) -> tuple[dict, ...]:
        if not self.path.is_file():
            return ()
        events = []
        previous = "0" * 64
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CloudBudgetError(f"invalid budget ledger row {number}: {exc}") from exc
            if event.get("prev_sha256") != previous or event.get("sha256") != _event_hash(event):
                raise CloudBudgetError(f"budget ledger hash chain failed at row {number}")
            if event.get("event") not in {"reserved", "committed", "released"}:
                raise CloudBudgetError(f"invalid budget event at row {number}")
            previous = event["sha256"]
            events.append(event)
        return tuple(events)

    def _lock(self):
        return _LedgerLock(self.path.with_suffix(self.path.suffix + ".lock"), self.lock_timeout_sec)


class _LedgerLock:
    def __init__(self, path: Path, timeout: float) -> None:
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while self.fd is None:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise CloudBudgetError(f"budget ledger lock remained busy: {self.path}")
                time.sleep(0.05)
        return self

    def __exit__(self, *_exc):
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


def _active_reservation(events, request_id: str) -> dict:
    matches = [event for event in events if event["request_id"] == request_id]
    if not matches or matches[-1]["event"] != "reserved":
        raise CloudBudgetError(f"cloud request has no active reservation: {request_id}")
    return matches[-1]


def _event_hash(event: dict) -> str:
    payload = {key: value for key, value in event.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as exc:
        raise CloudBudgetError(f"invalid monetary value: {value}") from exc


__all__ = ["BudgetSnapshot", "CloudBudgetError", "DailyBudgetLedger"]
