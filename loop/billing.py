"""
billing.py — keep the autoresearch loop on the Claude *subscription*, never the API.

The proposer and the meta-agent both drive the `claude` CLI in `-p` (print) mode.
`claude -p` bills your **subscription via OAuth by default** — there is no
`anthropic.Anthropic()` client anywhere in this repo, so the loop is NOT metered-API
work. But the OAuth-vs-metered boundary is wider than one variable. `claude -p`'s
credential/endpoint resolution is steered by a SET of `ANTHROPIC_*` vars, any of which
can move billing off the subscription:

  * ANTHROPIC_API_KEY    — a metered API key the CLI PREFERS when set.
  * ANTHROPIC_AUTH_TOKEN — an alternate bearer the CLI will use.
  * ANTHROPIC_BASE_URL   — redirects the endpoint (e.g. a metered gateway/proxy);
                           defaults to the public API, so dropping it is a no-op in
                           the common case and a correction when it points elsewhere.

So every place that spawns `claude` must spawn it with that whole set removed from the
child environment. Matching is **case-insensitive**: on Windows the process env block is
case-insensitive, so a lowercase `anthropic_api_key` the child would still resolve as the
canonical key must also be stripped. We do NOT touch the `CLAUDE_CODE_*` / `CLAUDECODE`
operational vars — those are how the harness runs the CLI and must be preserved.

This module is the single source of truth for (a) building that scrubbed environment,
(b) an in-place scrub for defense-in-depth at process startup (so workers that inherit
the env are safe even before the per-spawn scrub), and (c) a once-per-run banner that
tells the user which billing plane is active — billing certainty is the whole point, and
a silent scrub would give *less* visibility, not more.

Used by:
  * loop/policies.py    (ClaudeCodeProposer — the per-turn proposer spawn)
  * watcher.py          (run_meta_agent — the outer-loop spawn)
  * drawing_extract.py  (the optional Claude drawing-reader backend)
  * orchestrator.py / watcher.py / scripts/launch.* (startup scrub + the banner)
"""
from __future__ import annotations

import os

# The billing-steering vars to strip before any `claude` spawn. Names are compared
# case-insensitively (Windows env is case-insensitive). KEEP this to auth/routing vars
# only — never the CLAUDE_CODE_* operational vars the CLI needs to run.
BILLING_ENV_VARS = frozenset({
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
})

# Back-compat alias (older imports referenced API_KEY_VAR).
API_KEY_VAR = "ANTHROPIC_API_KEY"

_BILLING_VARS_LOWER = frozenset(v.lower() for v in BILLING_ENV_VARS)


def subscription_env(base: dict | None = None) -> dict:
    """Return a copy of the environment with every billing-steering var removed.

    Pass the result as `env=` to any `subprocess` call that spawns `claude`, so the CLI
    falls back to its OAuth/subscription credentials and the public endpoint instead of
    preferring a metered key/token or a redirected base URL set in the parent shell.

    Drops `BILLING_ENV_VARS` matched case-insensitively (a lowercase shadow leaks as the
    canonical var on Windows). Every other var — PATH, SystemRoot, CLAUDE_CODE_*, etc. —
    is preserved, so this is a copy-minus-a-known-set, never a rebuild-from-scratch.

    `base` defaults to `os.environ`; pass an explicit dict only for testing.
    """
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k.lower() not in _BILLING_VARS_LOWER}


def scrub_billing_env(base: dict | None = None) -> list[str]:
    """Remove the billing-steering vars from the process env IN PLACE; return the names
    removed. Call once at orchestrator/watcher startup so any child that inherits the env
    (workers spawned without an explicit env=) is billing-safe by default — defense in
    depth behind the per-spawn `subscription_env()` scrub. Idempotent.

    `base` defaults to `os.environ`; pass an explicit dict only for testing.
    """
    target = os.environ if base is None else base
    removed = [k for k in list(target.keys()) if k.lower() in _BILLING_VARS_LOWER]
    for k in removed:
        del target[k]
    return removed


def api_key_present(base: dict | None = None) -> bool:
    """True if any billing-steering AUTH var (a key or token — NOT the base URL, which
    defaults to the public endpoint) is set and non-empty, matched case-insensitively.

    Used by the banner to report whether a credential was found-and-ignored. The base URL
    is excluded here because its mere presence (usually the default) is not a 'credential
    found' event; the scrub still strips it regardless.
    """
    src = os.environ if base is None else base
    auth_vars = {"anthropic_api_key", "anthropic_auth_token"}
    return any(bool(v) for k, v in src.items() if k.lower() in auth_vars)


def billing_banner(base: dict | None = None) -> str:
    """A one-line, state-aware billing-plane banner string.

    - key set    -> it WILL be ignored (scrubbed) and the run uses the subscription.
    - key unset  -> the run uses the subscription with nothing to scrub.

    Either way the active plane is the subscription; the banner just makes which case
    you're in visible, so a key silently bleeding spend to the API can never happen
    unnoticed.
    """
    if api_key_present(base):
        return ("[billing] ANTHROPIC_* credential found in env -> IGNORED (the auth + "
                "base-URL vars are scrubbed before every `claude` spawn). Runs bill your "
                "SUBSCRIPTION via `claude -p` OAuth.")
    return ("[billing] No ANTHROPIC_* credential in env (auth + base-URL vars scrubbed "
            "regardless). Runs bill your SUBSCRIPTION via `claude -p` OAuth.")


def print_billing_banner(base: dict | None = None) -> None:
    """Print the banner once. Call from a launcher/orchestrator preamble, NOT per-turn."""
    print(billing_banner(base))
