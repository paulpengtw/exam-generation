"""File-backed admission state, independent of application deployments."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


@dataclass
class AdmissionState:
    state: Literal["paused", "open"]
    reason: str | None
    changed_at: str | None
    changed_by: str | None


def _closed(reason: str) -> AdmissionState:
    return AdmissionState("paused", reason, None, None)


def read_state(state_dir: Path) -> AdmissionState:
    """Re-read storage; only an explicit, valid open record admits generation."""
    try:
        data = json.loads((state_dir / "admission.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _closed("no admission state recorded")
    except (OSError, UnicodeError, ValueError):
        return _closed("admission state unreadable")
    if not isinstance(data, dict):
        return _closed("admission state unreadable")
    if data.get("state") not in ("paused", "open"):
        return _closed("unknown admission state")
    fields = {key: data.get(key) for key in ("reason", "changed_at", "changed_by")}
    if any(value is not None and not isinstance(value, str) for value in fields.values()):
        return _closed("admission state unreadable")
    return AdmissionState(state=data["state"], **fields)


def _write_state(state_dir: Path, state: AdmissionState) -> AdmissionState:
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=state_dir, prefix=".admission-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(asdict(state), handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, state_dir / "admission.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return state


def pause(
    state_dir: Path, reason: str | None = None, changed_by: str | None = None
) -> AdmissionState:
    return _write_state(
        state_dir, AdmissionState("paused", reason, datetime.now(UTC).isoformat(), changed_by)
    )


def open_gate(state_dir: Path, changed_by: str | None = None) -> AdmissionState:
    return _write_state(
        state_dir, AdmissionState("open", None, datetime.now(UTC).isoformat(), changed_by)
    )
