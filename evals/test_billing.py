"""
test_billing.py — the eval that locks the billing-plane guarantee.

Skills-as-code: the "test" for the subscription-billing invariant IS this eval. It
proves the property the whole loop depends on — a `claude -p` child must never inherit
a billing-steering var (a metered key/token, or a base URL pointing off the public
endpoint) — and it would FAIL loudly if a future edit narrowed the scrub back.

These were the findings of the cross-model adversarial /review pass (Claude + Codex
agreed); each test pins one fix so the regression can't come back:
  F1 — scrub the whole ANTHROPIC_* auth+routing SET, not just ANTHROPIC_API_KEY.
  F2 — match case-insensitively (Windows env is case-insensitive; lowercase leaks).
  F4 — scrub_billing_env() makes inherited-env children safe (defense in depth).
  F5 — the banner must not lie when the key is empty-string vs the auth set.

Pure + offline: operates on explicit dicts, no real `claude` spawn, no network.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
for _p in (str(_REPO), str(_REPO / "loop")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from loop.billing import (  # noqa: E402
    BILLING_ENV_VARS,
    api_key_present,
    billing_banner,
    scrub_billing_env,
    subscription_env,
)


# --------------------------------------------------------------------------- #
# F1 — the whole billing set is stripped, not just the API key
# --------------------------------------------------------------------------- #
def test_strips_api_key():
    env = {"PATH": "/x", "ANTHROPIC_API_KEY": "sk-secret"}
    assert "ANTHROPIC_API_KEY" not in subscription_env(env)
    assert subscription_env(env).get("PATH") == "/x"


def test_strips_base_url():
    """F1: ANTHROPIC_BASE_URL (a metered-proxy redirect vector) must be stripped —
    this is the var that was live in the real environment during review."""
    env = {"ANTHROPIC_BASE_URL": "https://metered.proxy.example/v1", "PATH": "/x"}
    assert "ANTHROPIC_BASE_URL" not in subscription_env(env)


def test_strips_auth_token():
    env = {"ANTHROPIC_AUTH_TOKEN": "tok-123", "PATH": "/x"}
    assert "ANTHROPIC_AUTH_TOKEN" not in subscription_env(env)


def test_strips_entire_known_set():
    env = {v: "x" for v in BILLING_ENV_VARS}
    env["PATH"] = "/x"
    out = subscription_env(env)
    assert not (set(out) & set(BILLING_ENV_VARS)), f"leaked: {set(out) & set(BILLING_ENV_VARS)}"
    assert out["PATH"] == "/x"


def test_preserves_operational_claude_vars():
    """The CLAUDE_CODE_* / CLAUDECODE vars are how the harness runs the CLI — never strip
    them, or `claude -p` itself breaks."""
    env = {"CLAUDE_CODE_SESSION_ID": "abc", "CLAUDECODE": "1",
           "ANTHROPIC_API_KEY": "sk-x", "PATH": "/x", "SystemRoot": "C:/WINDOWS"}
    out = subscription_env(env)
    assert out.get("CLAUDE_CODE_SESSION_ID") == "abc"
    assert out.get("CLAUDECODE") == "1"
    assert out.get("SystemRoot") == "C:/WINDOWS"
    assert "ANTHROPIC_API_KEY" not in out


# --------------------------------------------------------------------------- #
# F2 — case-insensitive match (Windows env is case-insensitive)
# --------------------------------------------------------------------------- #
def test_strips_lowercase_shadow():
    """F2: a lowercase anthropic_api_key would resolve as the canonical key on Windows;
    the scrub must drop it too."""
    env = {"anthropic_api_key": "sk-leak-lower", "PATH": "/x"}
    out = subscription_env(env)
    assert "anthropic_api_key" not in out
    assert not any(k.lower() == "anthropic_api_key" for k in out)


def test_strips_mixed_case_base_url():
    env = {"Anthropic_Base_Url": "https://proxy", "PATH": "/x"}
    out = subscription_env(env)
    assert not any(k.lower() == "anthropic_base_url" for k in out)


# --------------------------------------------------------------------------- #
# F4 — in-place scrub for inherited-env defense in depth
# --------------------------------------------------------------------------- #
def test_scrub_billing_env_mutates_and_reports():
    env = {"ANTHROPIC_API_KEY": "sk-x", "anthropic_base_url": "https://p", "PATH": "/x"}
    removed = scrub_billing_env(env)
    assert "ANTHROPIC_API_KEY" in removed
    assert "anthropic_base_url" in removed
    assert "ANTHROPIC_API_KEY" not in env
    assert not any(k.lower() in {v.lower() for v in BILLING_ENV_VARS} for k in env)
    assert env["PATH"] == "/x"


def test_scrub_billing_env_idempotent():
    env = {"ANTHROPIC_API_KEY": "sk-x", "PATH": "/x"}
    scrub_billing_env(env)
    assert scrub_billing_env(env) == []  # nothing left to remove
    assert env == {"PATH": "/x"}


# --------------------------------------------------------------------------- #
# F5 — banner truthfulness
# --------------------------------------------------------------------------- #
def test_banner_reports_found_when_key_present():
    assert "IGNORED" in billing_banner({"ANTHROPIC_API_KEY": "sk-x"})


def test_banner_reports_none_when_no_credential():
    assert "No ANTHROPIC_* credential" in billing_banner({"PATH": "/x"})


def test_empty_string_key_is_scrubbed_even_if_banner_neutral():
    """An empty-string key is not a 'credential found' (banner stays neutral), but the
    scrub still removes the var so it can't shadow anything downstream."""
    env = {"ANTHROPIC_API_KEY": "", "PATH": "/x"}
    assert api_key_present(env) is False           # empty != a usable credential
    assert "ANTHROPIC_API_KEY" not in subscription_env(env)  # but still stripped


def test_base_url_presence_is_not_a_credential_event():
    """Base URL alone (often the default) shouldn't make the banner cry 'credential
    found' — but it IS still scrubbed."""
    env = {"ANTHROPIC_BASE_URL": "https://api.anthropic.com", "PATH": "/x"}
    assert api_key_present(env) is False
    assert "ANTHROPIC_BASE_URL" not in subscription_env(env)


# --------------------------------------------------------------------------- #
# End-to-end: a real child subprocess cannot see the billing set
# --------------------------------------------------------------------------- #
def test_child_subprocess_cannot_see_billing_vars():
    """The property that actually protects billing: a child spawned with
    env=subscription_env() resolves the billing vars as absent, even on Windows where
    the env block is case-insensitive."""
    parent = dict(os.environ)
    parent["ANTHROPIC_API_KEY"] = "sk-PARENT-LEAK"
    parent["ANTHROPIC_BASE_URL"] = "https://metered.proxy.example"
    child = subprocess.run(
        [sys.executable, "-c",
         "import os;print('K='+repr(os.environ.get('ANTHROPIC_API_KEY')));"
         "print('U='+repr(os.environ.get('ANTHROPIC_BASE_URL')))"],
        capture_output=True, text=True, env=subscription_env(parent),
    )
    assert "K=None" in child.stdout, child.stdout
    assert "U=None" in child.stdout, child.stdout
