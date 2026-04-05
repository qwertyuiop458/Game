#!/usr/bin/env python3
"""Trigger /run-apk via issue comment, wait for workflow, download artifacts.

This automates the full GitHub UI flow in code:
1) post `/run-apk` comment to Issue/PR
2) wait for `run-apk.yml` run triggered by issue_comment
3) wait for completion
4) download and unpack `emulator-output` artifact
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

API_BASE = "https://api.github.com"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def request_json(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method=method, data=data)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "run-apk-via-issue-comment-script")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            if not payload:
                return {}
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {details}") from exc


def request_bytes(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "run-apk-via-issue-comment-script")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def post_trigger_comment(repo: str, issue_number: int, token: str, command: str) -> None:
    url = f"{API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    request_json(url, token, method="POST", body={"body": command})


def find_run(repo: str, workflow_file: str, token: str, started_after: dt.datetime, timeout_s: int, poll_s: int) -> dict:
    deadline = time.time() + timeout_s
    started_after_ts = started_after.timestamp()
    url = (
        f"{API_BASE}/repos/{repo}/actions/workflows/{urllib.parse.quote(workflow_file)}/runs"
        f"?event=issue_comment&per_page=30"
    )
    while time.time() < deadline:
        payload = request_json(url, token)
        runs = payload.get("workflow_runs", [])
        for run in runs:
            created_at = run.get("created_at")
            if not created_at:
                continue
            created_dt = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_dt.timestamp() >= started_after_ts:
                return run
        time.sleep(poll_s)
    raise TimeoutError("Timed out waiting for workflow run to appear")


def wait_run_completed(repo: str, run_id: int, token: str, timeout_s: int, poll_s: int) -> dict:
    deadline = time.time() + timeout_s
    url = f"{API_BASE}/repos/{repo}/actions/runs/{run_id}"
    while time.time() < deadline:
        run = request_json(url, token)
        if run.get("status") == "completed":
            return run
        time.sleep(poll_s)
    raise TimeoutError("Timed out waiting workflow run completion")


def download_artifact(repo: str, run_id: int, artifact_name: str, token: str, output_dir: Path) -> Path:
    artifacts_url = f"{API_BASE}/repos/{repo}/actions/runs/{run_id}/artifacts"
    payload = request_json(artifacts_url, token)
    artifacts = payload.get("artifacts", [])
    target = next((a for a in artifacts if a.get("name") == artifact_name), None)
    if not target:
        names = ", ".join(a.get("name", "<unknown>") for a in artifacts)
        raise RuntimeError(f"Artifact '{artifact_name}' not found. Available: {names}")

    zip_url = target["archive_download_url"]
    raw = request_bytes(zip_url, token)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{artifact_name}.zip"
    zip_path.write_bytes(raw)

    extract_dir = output_dir / artifact_name
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    return extract_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("REPO", "qwertyuiop458/Game"))
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--workflow-file", default="run-apk.yml")
    parser.add_argument("--artifact", default="emulator-output")
    parser.add_argument("--comment", default="/run-apk")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--run-timeout-seconds", type=int, default=1800)
    parser.add_argument("--discover-timeout-seconds", type=int, default=300)
    parser.add_argument("--output-dir", default=".artifacts/github-workflow")
    args = parser.parse_args()

    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        print("Set GH_TOKEN or GITHUB_TOKEN", file=sys.stderr)
        return 2

    started = dt.datetime.now(dt.timezone.utc)
    print(f"[{iso_now()}] Posting trigger comment '{args.comment}' to issue #{args.issue_number}")
    post_trigger_comment(args.repo, args.issue_number, token, args.comment)

    print(f"[{iso_now()}] Waiting for workflow run ({args.workflow_file})...")
    run = find_run(
        repo=args.repo,
        workflow_file=args.workflow_file,
        token=token,
        started_after=started - dt.timedelta(seconds=3),
        timeout_s=args.discover_timeout_seconds,
        poll_s=args.poll_seconds,
    )
    run_id = int(run["id"])
    run_url = run.get("html_url", "")
    print(f"[{iso_now()}] Found run id={run_id} url={run_url}")

    final_run = wait_run_completed(
        repo=args.repo,
        run_id=run_id,
        token=token,
        timeout_s=args.run_timeout_seconds,
        poll_s=args.poll_seconds,
    )
    conclusion = final_run.get("conclusion")
    print(f"[{iso_now()}] Run completed with conclusion={conclusion}")

    out_dir = Path(args.output_dir)
    extracted = download_artifact(args.repo, run_id, args.artifact, token, out_dir)
    print(f"[{iso_now()}] Artifact extracted to: {extracted}")

    result_env = extracted / "result.env"
    if result_env.exists():
        print(f"[{iso_now()}] result.env:\n{result_env.read_text(encoding='utf-8', errors='ignore')}")

    return 0 if conclusion == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
