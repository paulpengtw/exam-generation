"""The admission boundary must not capture read, preparation, or correction routes."""

import pytest

PASSTHROUGH_PATHS = [
    "/api/generate/preview",
    "/api/generate/resolve",
    "/api/plan-core-questions",
    "/api/generation-records/abc/modifications",
    "/api/generation-logs/x/exchanges",
    "/api/history",
    "/api/history/1",
    "/api/schemas",
    "/auth/magic-link",
    "/auth/session",
    "/health",
]


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/"])
def test_generation_entries(method, path):
    from gateway.admission import is_generation_entry

    assert is_generation_entry(method, path)


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/"])
def test_other_methods_are_not_generation(method, path):
    from gateway.admission import is_generation_entry

    assert not is_generation_entry(method, path)


@pytest.mark.parametrize("method", ["GET", "POST", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("path", PASSTHROUGH_PATHS + ["/", "/api/generate/extra"])
def test_passthrough_inventory(method, path):
    from gateway.admission import is_generation_entry

    assert not is_generation_entry(method, path)


def test_paused_contract():
    from gateway.admission import PAUSED_CODE, PAUSED_DETAIL

    assert PAUSED_DETAIL == "目前暫停受理新的出題請求，請稍後再試。"
    assert PAUSED_CODE == "GENERATION_ADMISSION_PAUSED"


# ---------------------------------------------------------------------------
# is_private_path tests
# ---------------------------------------------------------------------------


def test_is_private_path_internal():
    from gateway.admission import is_private_path

    assert is_private_path("/internal/drain")
    assert is_private_path("/internal/anything")
    assert is_private_path("/internal")


def test_is_private_path_non_internal():
    from gateway.admission import is_private_path

    assert not is_private_path("/api/generate")
    assert not is_private_path("/health")
    assert not is_private_path("/api/internal/foo")  # only /internal/* prefix
    assert not is_private_path("/api/history")
