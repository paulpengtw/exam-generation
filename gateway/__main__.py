"""Run the gateway as a module: python -m gateway."""

import os
from pathlib import Path

import uvicorn

from gateway.app import create_app
from gateway.release_controller import POLICY_SCHEMA, ReleaseController


def main() -> None:
    backend_url = os.environ["GATEWAY_BACKEND_URL"]
    state_dir = Path(os.environ.get("GATEWAY_STATE_DIR", "/var/lib/examgen-gate"))
    control_token = os.environ.get("GATEWAY_CONTROL_TOKEN") or None
    port = int(os.environ.get("PORT", "8000"))
    environment = os.environ.get("RELEASE_ENVIRONMENT", "production").strip() or "production"
    controller = ReleaseController(
        state_dir,
        environment=environment,
    )
    initial_build_id = os.environ.get("GATEWAY_RELEASED_BUILD_ID", "").strip()
    if initial_build_id and not (state_dir / "admission.json").exists():
        controller.initialize(
            {
                "schema": POLICY_SCHEMA,
                "environment": environment,
                "release_revision": int(os.environ.get("GATEWAY_RELEASE_REVISION", "1")),
                "released_build_id": initial_build_id,
                # First boot is fail-closed. The operator opens the existing
                # gate only after readiness evidence has been collected.
                "admission": "paused",
                "supported_recovery_formats": [
                    item.strip()
                    for item in os.environ.get(
                        "GATEWAY_SUPPORTED_RECOVERY_FORMATS", "exam-generation.recovery/1"
                    ).split(",")
                    if item.strip()
                ],
                "reader_version": os.environ.get("GATEWAY_READER_VERSION", "reader-1"),
            }
        )

    app = create_app(
        backend_url=backend_url,
        state_dir=state_dir,
        control_token=control_token,
        release_controller=controller,
    )

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
