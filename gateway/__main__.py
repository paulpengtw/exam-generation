"""Run the gateway as a module: python -m gateway."""

import os
from pathlib import Path

import uvicorn

from gateway.app import create_app


def main() -> None:
    backend_url = os.environ["GATEWAY_BACKEND_URL"]
    state_dir = Path(os.environ.get("GATEWAY_STATE_DIR", "/var/lib/examgen-gate"))
    control_token = os.environ.get("GATEWAY_CONTROL_TOKEN") or None
    port = int(os.environ.get("PORT", "8000"))

    app = create_app(
        backend_url=backend_url,
        state_dir=state_dir,
        control_token=control_token,
    )

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
