"""Send a signed brief webhook to the First Cut API and follow the run's progress.

uv run python scripts/send_webhook.py briefs/masa-bakery.md [--url http://localhost:8000]
uv run python scripts/send_webhook.py --gdoc <Google Doc URL> [--figma <Figma URL>]
"""

import argparse
import json
import time
from pathlib import Path

import httpx

from firstcut.api.security import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from firstcut.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("brief", type=Path, nargs="?", help="Markdown brief file.")
    parser.add_argument("--gdoc", help="Google Doc URL with the brief (instead of a file).")
    parser.add_argument("--figma", help="Figma file URL with the brand styles.")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--no-follow", action="store_true", help="Don't stream progress.")
    args = parser.parse_args()

    secret = get_settings().webhook_secret
    if secret is None:
        raise SystemExit("Set WEBHOOK_SECRET in .env first.")
    if bool(args.brief) == bool(args.gdoc):
        raise SystemExit("Pass a brief file or --gdoc, not both.")
    payload = {"brief": args.brief.read_text(encoding="utf-8")} if args.brief else {}
    payload |= {"gdoc_url": args.gdoc} if args.gdoc else {}
    payload |= {"figma_url": args.figma} if args.figma else {}
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign(secret.get_secret_value(), timestamp, body),
    }
    response = httpx.post(f"{args.url}/webhooks/brief", content=body, headers=headers)
    print(response.status_code, response.json())
    response.raise_for_status()
    if args.no_follow:
        return

    run_id = response.json()["run_id"]
    with httpx.stream("GET", f"{args.url}/runs/{run_id}/events", timeout=None) as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:])
                detail = event.get("node") or event.get("status") or ""
                print(f"[{event['type']}] {detail} {json.dumps(event.get('summary', ''))[:120]}")

    print(f"\nRun state: {args.url}/runs/{run_id}")
    print(
        f"Approve:  curl -X POST {args.url}/runs/{run_id}/approval "
        "-H 'Content-Type: application/json' -d '{\"approved\": true}'"
    )


if __name__ == "__main__":
    main()
