"""Read-only AWS preflight: python -m gonogo.preflight

Confirms the awsnew profile works in us-east-2 and lists the Claude inference profiles that
gonogo.aws.claude_profile() can choose from. It invokes no model and creates no resource.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from gonogo import aws


def main() -> None:
    s = aws.session()
    try:
        ident = s.client("sts").get_caller_identity()
    except Exception as exc:
        aws.raise_if_expired(exc)
        raise
    profiles = aws.list_inference_profiles()
    claude = sorted(
        p["inferenceProfileId"]
        for p in profiles
        if "anthropic.claude" in p["inferenceProfileId"]
        and p["inferenceProfileId"].split(".", 1)[0] in {"us", "global"}
    )
    print(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "profile": aws.load_settings().profile,
                "region": s.region_name,
                "account_last4": ident["Account"][-4:],
                "claude_profiles": claude,
                "selected": aws.pick_claude_profile(profiles),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
