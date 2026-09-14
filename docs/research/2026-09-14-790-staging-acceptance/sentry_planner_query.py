"""Read-only Sentry query for planner issues on the staging API project."""
import configparser, json, os, urllib.parse, urllib.request
from pathlib import Path
cfg = configparser.ConfigParser(); cfg.read(Path.home()/".sentryclirc")
token = os.environ.get("SENTRY_AUTH_TOKEN") or cfg.get("auth","token")
def get(path):
    req = urllib.request.Request("https://sentry.io/api/0/"+path,
        headers={"Authorization":"Bearer "+token})
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
out = {}
for proj in ("exam-generation-api-staging",):
    for q in ("Planner", "plan-core-questions", "malformed candidates"):
        try:
            issues = get(f"projects/cpengme/{proj}/issues/?" +
                         urllib.parse.urlencode({"query": q, "statsPeriod":"24h","limit":25}))
        except Exception as e:
            out[f"{proj}:{q}"] = f"error: {e}"; continue
        out[f"{proj}:{q}"] = [
            {"short_id": i["shortId"], "title": i["title"][:120], "level": i.get("level"),
             "count": i["count"], "first_seen": i["firstSeen"], "last_seen": i["lastSeen"],
             "permalink": i.get("permalink")}
            for i in issues]
print(json.dumps(out, ensure_ascii=False, indent=1))
