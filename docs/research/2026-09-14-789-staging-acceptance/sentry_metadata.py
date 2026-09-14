"""Read only exchange-warning metadata using the configured Sentry CLI token."""
import configparser
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

config = configparser.ConfigParser()
config.read(Path.home() / ".sentryclirc")
token = os.environ.get("SENTRY_AUTH_TOKEN") or config.get("auth", "token")


def get(path):
    req = urllib.request.Request(
        "https://sentry.io/api/0/" + path,
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


safe_keys = ("generation_log_id", "agent", "exchange_order", "outcome", "error_type", "error_module")
query = urllib.parse.urlencode({"query": "llm_exchanges", "limit": 100})
issues = get("projects/cpengme/exam-generation-api-staging/issues/?" + query)
output = []
for issue in issues:
    events = get("issues/" + issue["id"] + "/events/?full=true&per_page=100")
    rows = []
    for event in events:
        context = event.get("context", event.get("extra", {}))
        rows.append({
            "event_id": event.get("eventID"),
            "created_at": event.get("dateCreated"),
            "message": event.get("message"),
            "metadata": {key: context[key] for key in safe_keys if key in context},
            "has_exception": any(entry.get("type") == "exception" for entry in event.get("entries", [])),
            "has_request_body": any(entry.get("type") == "request" and bool(entry.get("data", {}).get("data")) for entry in event.get("entries", [])),
        })
    output.append({"id": issue["id"], "short_id": issue["shortId"], "count": issue["count"], "first_seen": issue["firstSeen"], "last_seen": issue["lastSeen"], "events": rows})
print(json.dumps(output, ensure_ascii=False, indent=2))
