"""Replay #780's three existing UI cases against pre-fix and integrated code.

Run after `npm ci` in web/. The baseline runs in a disposable copy; this script
never replaces files in the checkout. No browser, credentials, or LLM is used.
"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


EVIDENCE = Path(__file__).resolve().parent
REPO = EVIDENCE.parents[2]
WEB = REPO / "web"
BASELINE = "e6805ddb76db84fe84e97fccce7c7d06657e31c5"
SUITE = "src/pages/GeneratePage.history-prefill.test.tsx"
CASES = "keeps 全域池|keeps codes and offers|CONTROL:"


def run_case(web: Path, name: str, output_dir: Path) -> dict[str, object]:
    report = output_dir / f"{name}.json"
    result = subprocess.run(
        [
            "node", str(WEB / "node_modules/vitest/vitest.mjs"),
            "run", SUITE, "-t", CASES, "--maxWorkers=1",
            "--reporter=verbose", "--reporter=json", f"--outputFile.json={report}",
        ],
        cwd=web,
        capture_output=True,
        text=True,
        check=False,
    )
    log = (result.stdout + result.stderr).replace(str(web), "<web>")
    log = log.replace(str(output_dir), "<temporary-reports>")
    (EVIDENCE / f"race-{name}.log").write_text(log.rstrip() + "\n")
    data = json.loads(report.read_text())
    cases = [
        {"name": case["title"], "status": case["status"]}
        for suite in data["testResults"]
        for case in suite["assertionResults"]
        if case["status"] in {"passed", "failed"}
    ]
    return {"exit_code": result.returncode, "cases": cases}


def main() -> None:
    baseline_source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:web/src/components/ParamForm.tsx"], cwd=REPO,
    )
    with tempfile.TemporaryDirectory(prefix="examgen-786-race-") as temporary:
        directory = Path(temporary)
        baseline_web = directory / "web"
        shutil.copytree(
            WEB, baseline_web,
            ignore=shutil.ignore_patterns("node_modules", "dist", "*.tsbuildinfo"),
        )
        (baseline_web / "node_modules").symlink_to(WEB / "node_modules", target_is_directory=True)
        (baseline_web / "src/components/ParamForm.tsx").write_bytes(baseline_source)
        red = run_case(baseline_web, "red", directory)
        green = run_case(WEB, "green", directory)

    expected_red = ["failed", "failed", "passed"]
    expected_green = ["passed", "passed", "passed"]
    assert red["exit_code"] == 1 and [case["status"] for case in red["cases"]] == expected_red, red
    assert green["exit_code"] == 0 and [case["status"] for case in green["cases"]] == expected_green, green
    summary = {
        "baseline_param_form": BASELINE,
        "integrated_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
        ).strip(),
        "red": red,
        "green": green,
    }
    (EVIDENCE / "diagnostic-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print("PASS: pre-fix control green / both orderings red; integrated three cases green")


if __name__ == "__main__":
    main()
