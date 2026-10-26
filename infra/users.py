"""Create the sign-in users for a deployment, one per role, and keep their passwords in a file that git ignores.

    uv run python infra/users.py        creates any missing user and prints the user names, roles, and file

The password file (infra/users.json) is written on the machine that deploys and nowhere else. It is how a person
signs in to the AWS copy of the app. The evidence script reads the same file, so running it never changes a password.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gonogo import aws  # noqa: E402

FILE = ROOT / "infra" / "users.json"
USERS = {  # name -> role. Two stewards and two counsel, so the two-person rule can be played by two people.
    "pat-manager": "licensing_manager",
    "ann-steward": "steward",
    "ben-steward": "steward",
    "cy-counsel": "counsel",
    "dee-counsel": "counsel",
    "owen-owner": "ontology_owner",
    "fin-analyst": "finance_analyst",
    "aud-auditor": "auditor",
}


def stack_outputs(cf: Any, stack: str) -> dict[str, str]:
    return {o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]}


def ensure_users(session: Any, pool_id: str) -> dict[str, dict[str, str]]:
    """Every user exists in the pool, in its one group, with the password saved in FILE."""
    saved: dict[str, dict[str, str]] = json.loads(FILE.read_text()) if FILE.exists() else {}
    idp = session.client("cognito-idp")
    for name, role in USERS.items():
        known = saved.get(name, {})
        password = known.get("password") or secrets.token_urlsafe(18) + "aA1!"
        with contextlib.suppress(idp.exceptions.UsernameExistsException):
            idp.admin_create_user(UserPoolId=pool_id, Username=name, MessageAction="SUPPRESS")
        idp.admin_set_user_password(UserPoolId=pool_id, Username=name, Password=password, Permanent=True)
        idp.admin_add_user_to_group(UserPoolId=pool_id, GroupName=role, Username=name)
        saved[name] = {"password": password, "role": role}
    FILE.write_text(json.dumps(saved, indent=2) + "\n")
    FILE.chmod(0o600)
    return saved


if __name__ == "__main__":
    s = aws.session()
    pool = stack_outputs(s.client("cloudformation"), "gonogo-core")["UserPoolId"]
    users = ensure_users(s, pool)
    for n, u in users.items():
        print(f"{n:<16} {u['role']}")
    print(f"\nPasswords are in {FILE.relative_to(ROOT)}, which git ignores.")
