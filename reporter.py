#!/usr/bin/env python3
"""Robot Framework test reporter with Known Issue support.

Reads output.xml, builds a GitHub-flavoured HTML table of test results with
emoji status indicators, adds a "Known Issues" column, and posts the result as
a PR comment and/or GitHub step summary.

Environment variables (same interface as joonvena/robot-reporter Docker image):
  GH_ACCESS_TOKEN     GitHub token
  REPORT_PATH         Path to output.xml or a directory containing output.xml files
  REPOSITORY_OWNER    Repository owner
  REPOSITORY          Repository name
  COMMIT_SHA          Commit SHA (fallback when no PR)
  PR_ID               Pull request number
  SUMMARY             'true'/'false' — write to GitHub step summary (default: true)
  ONLY_SUMMARY        'true'/'false' — skip PR comment, only write summary (default: false)
  SHOW_PASSED_TESTS   'true'/'false' — include passed tests in table (default: true)
  FAILED_TESTS_ON_TOP 'true'/'false' — sort failed tests first (default: false)
  GITHUB_API_URL      GitHub API base URL
  GITHUB_STEP_SUMMARY Path to the step summary file
"""

import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_KNOWN_ISSUE_RE = re.compile(
    r"Known Issue Found:\s+(https?://\S+/browse/([\w-]+))"
)
_NAME_ANNOTATION_RE = re.compile(r"^(\[\*\*[\w-]+\*\*\]\(https?://\S+\)\s*)+")

STATUS_EMOJI = {
    "PASS": "\u2705",       # ✅
    "FAIL": "\u274C",       # ❌
    "SKIP": "\u23ED\uFE0F", # ⏭️
}


def _collect_known_issues(test_el):
    """Return list of (jira_id, url) for all Known Issue WARNs in a test element."""
    seen = {}
    for msg in test_el.iter("msg"):
        if msg.get("level") != "WARN":
            continue
        m = _KNOWN_ISSUE_RE.search(msg.text or "")
        if m:
            url, jira_id = m.group(1), m.group(2)
            seen.setdefault(jira_id, url)
    return [(jira_id, url) for jira_id, url in seen.items()]


def _strip_name_annotations(name):
    """Remove markdown link prefixes injected by annotate_known_issues.py."""
    return _NAME_ANNOTATION_RE.sub("", name).strip()


def _format_duration(elapsed_str):
    """Convert elapsed seconds string to human-readable duration."""
    try:
        secs = float(elapsed_str)
    except (TypeError, ValueError):
        return ""
    if secs < 60:
        return f"{secs:.1f}s"
    mins = int(secs // 60)
    return f"{mins}m {secs % 60:.0f}s"


def _walk_suite(suite_el, tests):
    """Recursively collect tests from a suite element, attaching the parent suite name."""
    suite_name = suite_el.get("name", "")
    for child in suite_el:
        if child.tag == "suite":
            _walk_suite(child, tests)
        elif child.tag == "test":
            status_el = child.find("status")
            if status_el is None:
                continue
            tests.append(
                {
                    "name": _strip_name_annotations(child.get("name", "")),
                    "status": status_el.get("status", "UNKNOWN"),
                    "elapsed": status_el.get("elapsed", ""),
                    "suite": suite_name,
                    "issues": _collect_known_issues(child),
                }
            )


def parse_output_xml(xml_path, failed_on_top=False):
    root = ET.parse(xml_path).getroot()
    tests = []
    for child in root:
        if child.tag == "suite":
            _walk_suite(child, tests)
    if failed_on_top:
        tests.sort(key=lambda t: (t["status"] == "PASS", t["status"] == "SKIP"))
    return tests


def _th(text):
    return f"<th>{text}</th>"


def _td(text):
    return f"<td>{text}</td>"


def _total_duration(tests):
    """Sum elapsed seconds across all tests and return formatted duration."""
    total = 0.0
    for t in tests:
        try:
            total += float(t["elapsed"])
        except (TypeError, ValueError):
            pass
    return _format_duration(str(total))


def _build_tests_table(tests):
    """Build an HTML table for a list of tests with Known Issues column."""
    header = (
        "<thead><tr>"
        + _th("Test")
        + _th("Status")
        + _th("\u23F1\uFE0F Duration")
        + _th("\u26A0\uFE0F Known Issues")
        + _th("Suite")
        + "</tr></thead>"
    )
    rows = []
    for t in tests:
        emoji = STATUS_EMOJI.get(t["status"], "\u2753")
        duration = _format_duration(t["elapsed"])
        issue_links = " ".join(
            f'<a href="{url}">{jid}</a>' for jid, url in t["issues"]
        )
        rows.append(
            "<tr>"
            + _td(t["name"])
            + _td(f"{emoji} {t['status']}")
            + _td(duration)
            + _td(issue_links)
            + _td(f"<code>{t['suite']}</code>")
            + "</tr>"
        )
    return "<table>" + header + "<tbody>" + "".join(rows) + "</tbody></table>"


def build_markdown(tests, show_passed=True):
    total = len(tests)
    passed = sum(1 for t in tests if t["status"] == "PASS")
    failed = sum(1 for t in tests if t["status"] == "FAIL")
    skipped = sum(1 for t in tests if t["status"] == "SKIP")
    with_issues = sum(1 for t in tests if t["issues"])
    pass_pct = f"{passed / total * 100:.0f}%" if total else "0%"
    issues_pct = f"{with_issues / total * 100:.0f}%" if total else "0%"

    # ── Summary table ────────────────────────────────────────────────────────
    summary_table = (
        "<table>"
        "<thead><tr>"
        + _th("\u2705 Passed")
        + _th("\u274C Failed")
        + _th("\u23ED\uFE0F Skipped")
        + _th("\u26A0\uFE0F Known Issues")
        + _th("Total")
        + _th("Pass %")
        + _th("\u23F1\uFE0F Duration")
        + "</tr></thead>"
        "<tbody><tr>"
        + _td(str(passed))
        + _td(str(failed))
        + _td(str(skipped))
        + _td(f"{with_issues} ({issues_pct})")
        + _td(str(total))
        + _td(pass_pct)
        + _td(_total_duration(tests))
        + "</tr></tbody>"
        "</table>"
    )

    lines = ["<h2>Robot Results</h2>", "", summary_table, ""]

    if not tests:
        lines.append("_No tests to display._")
        return "\n".join(lines)

    # ── Passed Tests table ───────────────────────────────────────────────────
    passed_tests = [t for t in tests if t["status"] == "PASS"]
    if show_passed and passed_tests:
        lines += ["<h2>Passed Tests</h2>", "", _build_tests_table(passed_tests), ""]

    # ── Failed Tests table ───────────────────────────────────────────────────
    failed_tests = [t for t in tests if t["status"] != "PASS"]
    if failed_tests:
        lines += ["<h2>Failed Tests</h2>", "", _build_tests_table(failed_tests), ""]

    return "\n".join(lines)


def _github_request(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, {}


def post_comment(token, owner, repo, pr_id, sha, markdown, api_url):
    if pr_id:
        url = f"{api_url}/repos/{owner}/{repo}/issues/{pr_id}/comments"
        label = f"PR #{pr_id}"
    elif sha:
        url = f"{api_url}/repos/{owner}/{repo}/commits/{sha}/comments"
        label = f"commit {sha[:8]}"
    else:
        print("reporter: no PR ID or commit SHA — skipping comment")
        return

    status, _ = _github_request("POST", url, token, {"body": markdown})
    if 200 <= status < 300:
        print(f"reporter: comment posted to {label}")
    else:
        print(f"reporter: failed to post comment to {label} (HTTP {status})", file=sys.stderr)


def main():
    env = os.environ.get

    report_path = env("REPORT_PATH", "reports")
    token = env("GH_ACCESS_TOKEN", "")
    owner = env("REPOSITORY_OWNER", "")
    repo = env("REPOSITORY", "")
    sha = env("COMMIT_SHA", "")
    pr_id = env("PR_ID", "")
    summary = env("SUMMARY", "true").lower() == "true"
    only_summary = env("ONLY_SUMMARY", "false").lower() == "true"
    show_passed = env("SHOW_PASSED_TESTS", "true").lower() == "true"
    failed_on_top = env("FAILED_TESTS_ON_TOP", "false").lower() == "true"
    api_url = env("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    step_summary_path = env("GITHUB_STEP_SUMMARY", "")

    if os.path.isfile(report_path):
        xml_path = report_path
    else:
        matches = glob.glob(
            os.path.join(report_path, "**", "output.xml"), recursive=True
        )
        if not matches:
            print(f"reporter: no output.xml found under {report_path!r}", file=sys.stderr)
            sys.exit(0)
        xml_path = matches[0]

    print(f"reporter: parsing {xml_path}")
    tests = parse_output_xml(xml_path, failed_on_top=failed_on_top)
    markdown = build_markdown(tests, show_passed=show_passed)

    if summary and step_summary_path:
        with open(step_summary_path, "a") as f:
            f.write(markdown + "\n")
        print("reporter: written to step summary")

    if only_summary:
        return

    if token:
        post_comment(token, owner, repo, pr_id, sha, markdown, api_url)
    else:
        print("reporter: no GH_ACCESS_TOKEN — skipping comment")


if __name__ == "__main__":
    main()
