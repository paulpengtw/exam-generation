#!/bin/sh
# 50-follow-release.sh — gateway follow-build hook for nginx:alpine
#
# Runs on every container start (before nginx).  Posts the frontend build_id
# from build-meta.json to the gateway follow endpoint so the gateway
# automatically tracks the deployed build.
#
# Inert unless both GATEWAY_FOLLOW_URL and GATEWAY_CONTROL_TOKEN are set.
# Never prints the token.
#
# META path is overridable for testing (test seam):
META="${FOLLOW_RELEASE_BUILD_META:-/usr/share/nginx/html/build-meta.json}"

if [ -z "${GATEWAY_FOLLOW_URL}" ] || [ -z "${GATEWAY_CONTROL_TOKEN}" ]; then
    echo "50-follow-release.sh: GATEWAY_FOLLOW_URL or GATEWAY_CONTROL_TOKEN not set; skipping follow" >&2
    exit 0
fi

# Check curl availability
if ! command -v curl >/dev/null 2>&1; then
    echo "50-follow-release.sh: curl not found; skipping follow" >&2
    exit 0
fi

# Extract build_id from build-meta.json using sed (POSIX-compatible, BusyBox safe)
BUILD_ID=""
BUILD_ID=$(sed -n 's/.*"build_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$META" 2>/dev/null | head -n 1) || true

if [ -z "${BUILD_ID}" ]; then
    echo "50-follow-release.sh: could not extract build_id from ${META}; skipping follow" >&2
    exit 0
fi

# Reject build_id with characters outside [A-Za-z0-9._:-]
case "${BUILD_ID}" in
    *[!A-Za-z0-9._:-]*)
        echo "50-follow-release.sh: build_id contains invalid characters; skipping follow" >&2
        exit 0
        ;;
esac

# POST with up to 3 attempts, 2s sleep between, --max-time 8 each
# (worst case: 3 * 8s + 2 * 2s = 28s < 30s)
ATTEMPTS=0
HTTP_CODE=""
while [ $ATTEMPTS -lt 3 ]; do
    ATTEMPTS=$((ATTEMPTS + 1))
    HTTP_CODE=$(curl --silent --show-error --max-time 8 \
        -o /dev/null \
        -w '%{http_code}' \
        -X POST \
        -H "X-Gateway-Control-Token: ${GATEWAY_CONTROL_TOKEN}" \
        -H "Content-Type: application/json" \
        --data "{\"build_id\":\"${BUILD_ID}\"}" \
        "${GATEWAY_FOLLOW_URL}" 2>/dev/null) || HTTP_CODE="000"

    # 2xx → success
    case "${HTTP_CODE}" in
        2[0-9][0-9])
            echo "50-follow-release.sh: follow succeeded (HTTP ${HTTP_CODE}) for build ${BUILD_ID}" >&2
            exit 0
            ;;
        4[0-9][0-9])
            echo "50-follow-release.sh: follow rejected (HTTP ${HTTP_CODE}) for build ${BUILD_ID}; not retrying" >&2
            exit 0
            ;;
        *)
            # 000 (curl failure) or 5xx → retry
            if [ $ATTEMPTS -lt 3 ]; then
                echo "50-follow-release.sh: attempt ${ATTEMPTS} failed (HTTP ${HTTP_CODE}); retrying in 2s" >&2
                sleep 2
            fi
            ;;
    esac
done

echo "50-follow-release.sh: follow failed after ${ATTEMPTS} attempts (last HTTP ${HTTP_CODE}) for build ${BUILD_ID}" >&2
exit 0
