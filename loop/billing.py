"""
billing.py — keep the autoresearch loop on the Claude *subscription*, never the API.

The proposer and the meta-agent both drive the `claude` CLI in `-p` (print) mode.
`claude -p` bills your **subscription via OAuth by default** — there is no
`anthropic.Anthropic()` client anywhere in this repo, so the loop is NOT metered-API
work. There is exactly ONE way it can accidentally hit the metered API:

    `claude -p` PREFERS the `ANTHROPIC_API_KEY` env var when it is set.

So every place that spawns `claude` must spawn it with that var removed from the
child environment. This module is the single source of truth for (a) building that
scrubbed environment and (b) printing a once-per-run banner that tells the user which
billing plane is active — billing certainty is the whole point, and a silent scrub
would give *less* visibility, not more.

Used by:
  * loop/policies.py   (ClaudeCodeProposer — the per-turn proposer spawn)
  * watcher.py         (run_meta_agent — the outer-loop spawn)
  * orchestrator.py / scripts/launch.* (the once-per-run banner)
"""
from __future__ import annotations

import os

API_KEY_VAR = "ANTHROPIC_API_KEY"


def subscription_env(base: dict | None = None) -> dict:
    """Return a copy of the environment with ANTHROPIC_API_KEY removed.

    Pass the result as `env=` to any `subprocess` call that spawns `claude`, so the
    CLI falls back to its OAuth/subscription credentials instead of preferring a
    metered API key that happens to be set in the parent shell.

    `base` defaults to `os.environ`; pass an explicit dict only for testing.
    """
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k != API_KEY_VAR}


def api_key_present(base: dict | None = None) -> bool:
    """True if ANTHROPIC_API_KEY is set (and non-empty) in the given environment."""
    src = os.environ if base is None else base
    return bool(src.get(API_KEY_VAR))


def billing_banner(base: dict | None = None) -> str:
    """A one-line, state-aware billing-plane banner string.

    - key set    -> it WILL be ignored (scrubbed) and the run uses the subscription.
    - key unset  -> the run uses the subscription with nothing to scrub.

    Either way the active plane is the subscription; the banner just makes which case
    you're in visible, so a key silently bleeding spend to the API can never happen
    unnoticed.
    """
    if api_key_present(base):
        return ("[billing] ANTHROPIC_API_KEY found in env -> IGNORED (scrubbed before "
                "each `claude` spawn). Runs bill your SUBSCRIPTION via `claude -p` OAuth.")
    return ("[billing] No ANTHROPIC_API_KEY in env. Runs bill your SUBSCRIPTION via "
            "`claude -p` OAuth.")


def print_billing_banner(base: dict | None = None) -> None:
    """Print the banner once. Call from a launcher/orchestrator preamble, NOT per-turn."""
    print(billing_banner(base))
