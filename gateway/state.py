"""File-backed admission state, independent of application deployments."""

import json
import os
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


@dataclass
class AdmissionState:
    state: Literal["paused", "open"]
    reason: str | None
    changed_at: str | None
    changed_by: str | None
    # Release-policy fields are stored in this same file so the gate and the
    # browser/backend authority can never select different pause switches.
    schema: str | None = None
    environment: str | None = None
    release_revision: int | None = None
    released_build_id: str | None = None
    admission: Literal["open", "paused", "preparing"] | None = None
    supported_recovery_formats: list[str] = field(default_factory=list)
    reader_version: str | None = None
    artifacts: dict[str, Any] | None = None
    preparation: dict[str, Any] | None = None


def _closed(reason: str) -> AdmissionState:
    return AdmissionState("paused", reason, None, None)


_POLICY_FIELDS = (
    "schema",
    "environment",
    "release_revision",
    "released_build_id",
    "admission",
    "supported_recovery_formats",
    "reader_version",
    "artifacts",
    "preparation",
)


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
    policy_fields = {key: data.get(key) for key in _POLICY_FIELDS}
    # Legacy gate records are written with an empty format list by the
    # extended dataclass.  The schema (or another required field) is what
    # distinguishes a controller record from that legacy shape.
    supplied_policy = data.get("schema") is not None or any(
        data.get(key) is not None
        for key in (
            "environment",
            "release_revision",
            "released_build_id",
            "admission",
            "reader_version",
            "artifacts",
            "preparation",
        )
    )
    if supplied_policy:
        if not isinstance(policy_fields["schema"], str):
            return _closed("admission state unreadable")
        if not isinstance(policy_fields["environment"], str):
            return _closed("admission state unreadable")
        if not isinstance(policy_fields["release_revision"], int) or isinstance(
            policy_fields["release_revision"], bool
        ):
            return _closed("admission state unreadable")
        if not isinstance(policy_fields["released_build_id"], str):
            return _closed("admission state unreadable")
        if policy_fields["admission"] not in ("open", "paused", "preparing"):
            return _closed("admission state unreadable")
        if not isinstance(policy_fields["supported_recovery_formats"], list) or any(
            not isinstance(item, str) for item in policy_fields["supported_recovery_formats"]
        ):
            return _closed("admission state unreadable")
        if policy_fields["reader_version"] is not None and not isinstance(
            policy_fields["reader_version"], str
        ):
            return _closed("admission state unreadable")
        if policy_fields["artifacts"] is not None and not isinstance(
            policy_fields["artifacts"], dict
        ):
            return _closed("admission state unreadable")
        if policy_fields["preparation"] is not None and not isinstance(
            policy_fields["preparation"], dict
        ):
            return _closed("admission state unreadable")
        expected_state = "open" if policy_fields["admission"] == "open" else "paused"
        if data["state"] != expected_state:
            return _closed("admission state unreadable")
    else:
        legacy_formats = data.get("supported_recovery_formats", [])
        if not isinstance(legacy_formats, list) or any(
            not isinstance(item, str) for item in legacy_formats
        ):
            return _closed("admission state unreadable")
        policy_fields = {key: None for key in _POLICY_FIELDS}
        policy_fields["supported_recovery_formats"] = legacy_formats
    return AdmissionState(state=data["state"], **fields, **policy_fields)


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


def write_state(state_dir: Path, state: AdmissionState) -> AdmissionState:
    """Persist one complete gate/controller record atomically."""
    return _write_state(state_dir, state)


def _preserved_policy(state_dir: Path, admission: Literal["open", "paused"]) -> dict[str, Any]:
    """Return policy fields from the current record, if it has a policy."""
    current = read_state(state_dir)
    if current.schema is None:
        return {
            "schema": None,
            "environment": None,
            "release_revision": None,
            "released_build_id": None,
            "admission": None,
            "supported_recovery_formats": [],
            "reader_version": None,
            "artifacts": None,
            "preparation": None,
        }
    return {
        "schema": current.schema,
        "environment": current.environment,
        "release_revision": current.release_revision,
        "released_build_id": current.released_build_id,
        "admission": admission,
        "supported_recovery_formats": deepcopy(current.supported_recovery_formats),
        "reader_version": current.reader_version,
        "artifacts": deepcopy(current.artifacts),
        "preparation": deepcopy(current.preparation),
    }


def pause(
    state_dir: Path, reason: str | None = None, changed_by: str | None = None
) -> AdmissionState:
    return _write_state(
        state_dir,
        AdmissionState(
            "paused",
            reason,
            datetime.now(UTC).isoformat(),
            changed_by,
            **_preserved_policy(state_dir, "paused"),
        ),
    )


def open_gate(state_dir: Path, changed_by: str | None = None) -> AdmissionState:
    return _write_state(
        state_dir,
        AdmissionState(
            "open",
            None,
            datetime.now(UTC).isoformat(),
            changed_by,
            **_preserved_policy(state_dir, "open"),
        ),
    )
