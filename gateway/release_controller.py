"""Live release-policy contract and controller state transitions.

The controller deliberately stores its release record in the gateway's
existing ``admission.json`` file.  That file is the only independent pause
switch: the gateway, browser metadata route, and backend authority reader all
observe the same record on every request.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from gateway.state import AdmissionState, read_state, write_state

POLICY_SCHEMA = "exam-generation.release-policy/1"
ADMISSION_STATES = frozenset({"open", "paused", "preparing"})
DEFAULT_READER_VERSION = "reader-1"
DEFAULT_MAX_DRAIN_AGE_SECONDS = 15.0
_DRAIN_COUNTERS = (
    "active_runs",
    "active_workers",
    "open_streams",
    "pending_deliveries",
    "pending_persistence",
    "renderer_leases_held",
)


class ReleasePolicyError(ValueError):
    """A policy or transition cannot safely be accepted."""


def _require_string(raw: dict[str, Any], field: str, *, nonempty: bool = True) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ReleasePolicyError(f"release policy field {field!r} is invalid")
    return value


def _validate_artifact(value: object, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ReleasePolicyError(f"release policy field {field!r} is invalid")
    build_id = value.get("build_id")
    revision = value.get("release_revision")
    reader = value.get("reader_version")
    if not isinstance(build_id, str) or not build_id.strip():
        raise ReleasePolicyError(f"release artifact {field!r} has no build_id")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ReleasePolicyError(f"release artifact {field!r} has invalid release_revision")
    if not isinstance(reader, str) or not reader.strip():
        raise ReleasePolicyError(f"release artifact {field!r} has no reader_version")
    return deepcopy(value)


def _validate_artifacts(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ReleasePolicyError("release policy field 'artifacts' is invalid")
    current = _validate_artifact(value.get("current"), "current")
    rollback = _validate_artifact(value.get("prepared_rollback"), "prepared_rollback")
    transition = value.get("transition", [])
    if not isinstance(transition, list) or any(not isinstance(item, dict) for item in transition):
        raise ReleasePolicyError("release policy field 'artifacts.transition' is invalid")
    return {
        "current": current,
        "prepared_rollback": rollback,
        "transition": deepcopy(transition),
    }


def parse_policy(raw: object, *, expected_environment: str | None = None) -> dict[str, Any]:
    """Validate and copy the public release-policy contract.

    Extra fields are retained so the controller can carry transition evidence
    without making the browser/backend contract brittle.  Required fields are
    intentionally strict; malformed authority data is unavailable, never an
    implicit open gate.
    """
    if not isinstance(raw, dict):
        raise ReleasePolicyError("release policy must be a JSON object")
    if raw.get("schema") != POLICY_SCHEMA:
        raise ReleasePolicyError("unknown release policy schema")
    environment = _require_string(raw, "environment")
    if expected_environment is not None and environment != expected_environment:
        raise ReleasePolicyError("release policy environment does not match controller")

    revision = raw.get("release_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ReleasePolicyError("release policy release_revision is invalid")
    released_build_id = _require_string(raw, "released_build_id")
    admission = raw.get("admission")
    if admission not in ADMISSION_STATES:
        raise ReleasePolicyError("release policy admission is invalid")
    formats = raw.get("supported_recovery_formats")
    if not isinstance(formats, list) or any(not isinstance(item, str) for item in formats):
        raise ReleasePolicyError("release policy supported_recovery_formats is invalid")

    reader_version = raw.get("reader_version")
    if reader_version is not None and (not isinstance(reader_version, str) or not reader_version):
        raise ReleasePolicyError("release policy reader_version is invalid")
    artifacts = _validate_artifacts(raw.get("artifacts"))
    preparation = raw.get("preparation")
    if preparation is not None and not isinstance(preparation, dict):
        raise ReleasePolicyError("release policy preparation is invalid")

    parsed = deepcopy(raw)
    parsed.update(
        {
            "schema": POLICY_SCHEMA,
            "environment": environment,
            "release_revision": revision,
            "released_build_id": released_build_id,
            "admission": admission,
            "supported_recovery_formats": deepcopy(formats),
            "reader_version": reader_version,
            "artifacts": artifacts,
            "preparation": deepcopy(preparation),
        }
    )
    return parsed


def _policy_from_state(state: AdmissionState) -> dict[str, Any] | None:
    if state.schema is None:
        return None
    return {
        "schema": state.schema,
        "environment": state.environment,
        "release_revision": state.release_revision,
        "released_build_id": state.released_build_id,
        "admission": state.admission,
        "supported_recovery_formats": deepcopy(state.supported_recovery_formats or []),
        "reader_version": state.reader_version,
        "artifacts": deepcopy(state.artifacts),
        "preparation": deepcopy(state.preparation),
    }


def _artifact_from_policy(policy: dict[str, Any]) -> dict[str, Any]:
    artifacts = policy.get("artifacts")
    if isinstance(artifacts, dict) and isinstance(artifacts.get("current"), dict):
        return deepcopy(artifacts["current"])
    return {
        "build_id": policy["released_build_id"],
        "release_revision": policy["release_revision"],
        "reader_version": policy.get("reader_version") or DEFAULT_READER_VERSION,
    }


def _target_artifact(target: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "build_id": target["build_id"],
        "release_revision": target["release_revision"],
        "reader_version": target.get("reader_version")
        or policy.get("reader_version")
        or DEFAULT_READER_VERSION,
        **(
            deepcopy(target.get("artifact_metadata"))
            if isinstance(target.get("artifact_metadata"), dict)
            else {}
        ),
    }


def _now_iso(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class ReleaseController:
    """File-backed live controller for release preparation and publication."""

    def __init__(
        self,
        state_dir: Path,
        *,
        environment: str,
        max_drain_age_seconds: float = DEFAULT_MAX_DRAIN_AGE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not environment.strip():
            raise ValueError("controller environment must not be empty")
        self.state_dir = state_dir
        self.environment = environment
        self.max_drain_age_seconds = max(0.0, max_drain_age_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def read_policy(self) -> dict[str, Any] | None:
        """Read and validate current policy from disk; never return a cache."""
        state = read_state(self.state_dir)
        raw = _policy_from_state(state)
        if raw is None:
            return None
        try:
            return parse_policy(raw, expected_environment=self.environment)
        except ReleasePolicyError:
            return None

    def initialize(self, raw: dict[str, Any]) -> dict[str, Any]:
        policy = parse_policy(raw, expected_environment=self.environment)
        current = self.read_policy()
        if current is not None:
            if current != policy:
                raise ReleasePolicyError("release controller is already initialized")
            return current
        return self._write(policy, changed_by="controller", reason="controller initialized")

    def prepare_target(
        self,
        raw_target: dict[str, Any],
        *,
        transition_assets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current = self._require_policy()
        target = self._normalise_target(raw_target, current)
        if target["release_revision"] <= current["release_revision"]:
            raise ReleasePolicyError("target release_revision must increase")
        current_artifact = _artifact_from_policy(current)
        existing_artifacts = current.get("artifacts") or {}
        old_transition = existing_artifacts.get("transition", [])
        additions = transition_assets or []
        if any(not isinstance(item, dict) for item in additions):
            raise ReleasePolicyError("transition assets must be objects")
        updated = deepcopy(current)
        updated.update(
            {
                "admission": "preparing",
                "preparation": {
                    "target": target,
                    "prepared_at": _now_iso(self._clock),
                },
                "artifacts": {
                    "current": current_artifact,
                    "prepared_rollback": deepcopy(current_artifact),
                    "transition": deepcopy(old_transition) + deepcopy(additions),
                },
            }
        )
        return self._write(updated, changed_by="controller", reason="release preparation")

    def publish_target(self, evidence: dict[str, Any]) -> dict[str, Any]:
        current = self._require_policy()
        preparation = current.get("preparation")
        if current["admission"] != "preparing" or not isinstance(preparation, dict):
            raise ReleasePolicyError("release target is not prepared")
        target = preparation.get("target")
        if not isinstance(target, dict):
            raise ReleasePolicyError("prepared release target is invalid")
        self._validate_switch_evidence(evidence, target)

        old_artifact = _artifact_from_policy(current)
        new_artifact = _target_artifact(target, current)
        updated = deepcopy(current)
        updated.update(
            {
                "release_revision": target["release_revision"],
                "released_build_id": target["build_id"],
                "admission": "paused",
                "reader_version": new_artifact["reader_version"],
                "supported_recovery_formats": deepcopy(
                    target.get("supported_recovery_formats")
                    or current["supported_recovery_formats"]
                ),
                "preparation": None,
                "artifacts": {
                    "current": new_artifact,
                    "prepared_rollback": old_artifact,
                    "transition": deepcopy((current.get("artifacts") or {}).get("transition", [])),
                },
            }
        )
        # Publishing never opens admission. The operator must use the same
        # persistent gate after a later positive readiness check.
        return self._write(updated, changed_by="controller", reason="release target published")

    def retire_artifact(self, artifact_ref: str, evidence: dict[str, Any]) -> dict[str, Any]:
        current = self._require_policy()
        self._validate_retirement_evidence(evidence)
        artifacts = deepcopy(current.get("artifacts") or {})
        transition = artifacts.get("transition", [])
        if not isinstance(transition, list):
            raise ReleasePolicyError("transition assets are invalid")

        current_identity = _artifact_identity(artifacts.get("current"))
        rollback = artifacts.get("prepared_rollback")
        rollback_matches = isinstance(rollback, dict) and artifact_ref in {
            str(rollback.get("name", "")),
            str(rollback.get("build_id", "")),
        }
        if rollback_matches:
            if _artifact_identity(rollback) == current_identity:
                raise ReleasePolicyError("current artifact is protected")
            artifacts["prepared_rollback"] = None
            updated = deepcopy(current)
            updated["artifacts"] = artifacts
            return self._write(updated, changed_by="controller", reason="rollback artifact retired")

        matches = [
            item
            for item in transition
            if isinstance(item, dict)
            and artifact_ref in {str(item.get("name", "")), str(item.get("build_id", ""))}
        ]
        if not matches:
            raise ReleasePolicyError("retirement artifact is not a transition asset")
        if any(_artifact_identity(item) == current_identity for item in matches):
            raise ReleasePolicyError("current artifact is protected")
        artifacts["transition"] = [item for item in transition if item not in matches]
        updated = deepcopy(current)
        updated["artifacts"] = artifacts
        return self._write(updated, changed_by="controller", reason="transition asset retired")

    def _require_policy(self) -> dict[str, Any]:
        policy = self.read_policy()
        if policy is None:
            raise ReleasePolicyError("release authority unavailable")
        return policy

    def _normalise_target(self, raw: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ReleasePolicyError("release target must be an object")
        build_id = raw.get("build_id")
        revision = raw.get("release_revision")
        if not isinstance(build_id, str) or not build_id.strip():
            raise ReleasePolicyError("release target build_id is invalid")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ReleasePolicyError("release target release_revision is invalid")
        reader_version = raw.get("reader_version") or current.get("reader_version")
        if not isinstance(reader_version, str) or not reader_version.strip():
            raise ReleasePolicyError("release target reader_version is invalid")
        target = deepcopy(raw)
        target.update(
            {
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": reader_version,
                "supported_recovery_formats": deepcopy(
                    raw.get("supported_recovery_formats")
                    or current["supported_recovery_formats"]
                ),
            }
        )
        if not isinstance(target["supported_recovery_formats"], list) or any(
            not isinstance(item, str) for item in target["supported_recovery_formats"]
        ):
            raise ReleasePolicyError("release target recovery formats are invalid")
        if raw.get("environment", self.environment) != self.environment:
            raise ReleasePolicyError("release target environment does not match controller")
        return target

    def _write(
        self,
        policy: dict[str, Any],
        *,
        changed_by: str,
        reason: str | None,
    ) -> dict[str, Any]:
        parsed = parse_policy(policy, expected_environment=self.environment)
        is_open = parsed["admission"] == "open"
        effective_reason: str | None = None if is_open else reason
        state = AdmissionState(
            state="open" if is_open else "paused",
            reason=effective_reason,
            changed_at=_now_iso(self._clock),
            changed_by=changed_by,
            schema=parsed["schema"],
            environment=parsed["environment"],
            release_revision=parsed["release_revision"],
            released_build_id=parsed["released_build_id"],
            admission=parsed["admission"],
            supported_recovery_formats=parsed["supported_recovery_formats"],
            reader_version=parsed.get("reader_version"),
            artifacts=parsed.get("artifacts"),
            preparation=parsed.get("preparation"),
        )
        write_state(self.state_dir, state)
        return parsed

    def follow_build(self, build_id: str) -> dict[str, Any]:
        """Atomically advance released_build_id to build_id without drain evidence.

        Designed for staging: the frontend nginx entrypoint hook calls this on
        every container start so the gateway policy tracks the deployed bundle.
        Admission state (open/paused) is not changed.
        """
        _require_string({"build_id": build_id}, "build_id")
        current = self._require_policy()
        if current["admission"] == "preparing":
            raise ReleasePolicyError("release preparation is in progress")
        if build_id == current["released_build_id"]:
            return current
        old_artifact = _artifact_from_policy(current)
        new_revision = current["release_revision"] + 1
        new_artifact = {
            "build_id": build_id,
            "release_revision": new_revision,
            "reader_version": current.get("reader_version") or DEFAULT_READER_VERSION,
        }
        existing_artifacts = current.get("artifacts") or {}
        updated = deepcopy(current)
        updated["release_revision"] = new_revision
        updated["released_build_id"] = build_id
        updated["reader_version"] = new_artifact["reader_version"]
        updated["artifacts"] = {
            "current": new_artifact,
            "prepared_rollback": old_artifact,
            "transition": deepcopy(existing_artifacts.get("transition", [])),
        }
        reason = (
            read_state(self.state_dir).reason
            if current["admission"] != "open"
            else "staging follow"
        )
        return self._write(
            updated,
            changed_by="controller",
            reason=reason,
        )

    def _validate_switch_evidence(self, evidence: dict[str, Any], target: dict[str, Any]) -> None:
        self._validate_pending_admissions(evidence)
        snapshots = self._validate_drain_evidence(evidence)
        if not snapshots:
            raise ReleasePolicyError("drain evidence is missing")
        routes = evidence.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ReleasePolicyError("route evidence is missing")
        expected_routes = evidence.get("expected_routes")
        if not isinstance(expected_routes, list) or not expected_routes:
            raise ReleasePolicyError("route inventory is missing")
        if {str(item) for item in expected_routes} != {
            str(item.get("name")) for item in routes if isinstance(item, dict)
        }:
            raise ReleasePolicyError("route evidence is incomplete")
        seen: set[str] = set()
        for route in routes:
            if not isinstance(route, dict):
                raise ReleasePolicyError("route evidence is invalid")
            name = route.get("name")
            if not isinstance(name, str) or not name or name in seen:
                raise ReleasePolicyError("route evidence has duplicate or missing route")
            seen.add(name)
            self._validate_route(route, target)

    def _validate_route(self, route: dict[str, Any], target: dict[str, Any]) -> None:
        metadata = route.get("metadata") if isinstance(route.get("metadata"), dict) else route
        if (
            metadata.get("build_id") != target["build_id"]
            or metadata.get("release_revision") != target["release_revision"]
            or metadata.get("reader_version") != target["reader_version"]
        ):
            raise ReleasePolicyError(
                f"route {route.get('name', '<unknown>')} metadata does not match target"
            )

    def _validate_pending_admissions(self, evidence: dict[str, Any]) -> None:
        pending = evidence.get("pending_admissions")
        if not isinstance(pending, int) or isinstance(pending, bool) or pending != 0:
            raise ReleasePolicyError("pending admissions prevent switching")

    def _validate_drain_evidence(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        snapshots = evidence.get("drain_snapshots")
        if not isinstance(snapshots, list):
            raise ReleasePolicyError("drain evidence is missing")
        expected_instances = evidence.get("instances")
        if not isinstance(expected_instances, list) or not expected_instances or any(
            not isinstance(item, str) for item in expected_instances
        ):
            raise ReleasePolicyError("drain inventory is invalid")
        ids: set[str] = set()
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                raise ReleasePolicyError("drain evidence is invalid")
            instance_id = snapshot.get("instance_id")
            if not isinstance(instance_id, str) or not instance_id or instance_id in ids:
                raise ReleasePolicyError("drain evidence has duplicate or missing instance")
            ids.add(instance_id)
            captured_at = snapshot.get("captured_at")
            try:
                captured = datetime.fromisoformat(captured_at)
                if captured.tzinfo is None:
                    captured = captured.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                raise ReleasePolicyError("drain evidence is stale") from None
            age = (now - captured.astimezone(UTC)).total_seconds()
            if age > self.max_drain_age_seconds:
                raise ReleasePolicyError("drain evidence is stale")
            if any(snapshot.get(counter) != 0 for counter in _DRAIN_COUNTERS):
                raise ReleasePolicyError("drain evidence is nonzero")
            if snapshot.get("integrity_errors") != 0 or snapshot.get("quiescent") is not True:
                raise ReleasePolicyError("drain evidence is not positive")
        if ids != set(expected_instances):
            raise ReleasePolicyError("drain evidence does not cover inventory")
        return snapshots

    def _validate_retirement_evidence(self, evidence: dict[str, Any]) -> None:
        if not isinstance(evidence, dict):
            raise ReleasePolicyError("retirement evidence is missing")
        self._validate_pending_admissions(evidence)
        if not self._validate_drain_evidence(evidence):
            raise ReleasePolicyError("retirement evidence is missing")


def _artifact_identity(value: object) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    build_id = value.get("build_id")
    revision = value.get("release_revision")
    if isinstance(build_id, str) and isinstance(revision, int):
        return build_id, revision
    return None
