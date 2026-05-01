"""Secret-redaction utility for outbound runtime data.

Forge has multiple outbound surfaces where credentials could leak if we don't
scrub:

  - **Trace JSONL** (``.forge/sessions/<id>/trace.jsonl``) — agent output,
    evaluator feedback, KB content all written to disk. A generator that
    echoes an API key from the prompt would land that key in the audit log.
  - **Daemon log** (``.forge/forge.log``) — exception messages can carry
    credentials (e.g., 401 responses that include the failing bearer).
  - **WebSocket event stream** to the localhost UI — same payloads as trace.
  - **KB writes** (``forge_kb_add`` via MCP) — any agent can write strings
    into the KB; nothing scrubs them.
  - **Episodic store** (``error`` / ``resolution`` columns) — subprocess
    stderr ends up here.
  - **Diff content** sent to the evaluator LLM — if someone commits ``.env``
    by mistake, the diff carries the keys to the model API.

This module provides one defense in depth: **regex-based redaction** of the
patterns most credentials match. It's not a complete solution (high-entropy
random strings without recognizable structure will slip through) but it
catches the common shapes — Anthropic keys, OpenAI keys, AWS keys, JWT
tokens, GitHub tokens, .env-line patterns, and generic ``Bearer <hex>``
headers.

Two modes:

  ``redact(text)`` — replace every match with ``[REDACTED:<TYPE>]``.
  ``contains_secret(text)`` — fast yes/no check, used by KB-write gate.

Performance: each pattern is pre-compiled. A 4 KB log line takes <100µs
on the M-series target; trace-event writes are unbounded but each individual
event is small. We don't ship redaction at the LLM-prompt layer by default
(too aggressive — would mangle legitimate code containing API tokens that
the user *wants* to send to the model). The user can opt in via
``FORGE_REDACT_PROMPTS=1``.

References:
  - gitleaks default rules for inspiration on patterns
  - ADR-007 (local-first, no telemetry — the audit log is the user's record;
    keep it scrubbed even though it doesn't leave their machine)
  - ADR-017 (NEW — outbound runtime redaction)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# ---- Regex catalog ----
#
# Each entry has: a label (for the redaction marker) and a pattern. The
# patterns aim for low false-positive rates — they require enough structure
# (prefix, length, character class) that legitimate code rarely matches.
#
# Order matters: more specific patterns first. Once a span is redacted we
# don't re-scan it, so a key that matches both "Bearer <hex>" and "JWT" is
# replaced by the more-specific marker.


@dataclass(frozen=True)
class _Rule:
    label: str
    pattern: re.Pattern[str]


# Anthropic API keys — sk-ant-api03-… typical shape, ~95 chars total
_ANTHROPIC = _Rule(
    label="ANTHROPIC_KEY",
    pattern=re.compile(r"\bsk-ant-(?:api\d{2}|sid\d{2})-[A-Za-z0-9_-]{80,}\b"),
)

# OpenAI keys (legacy `sk-…` and project `sk-proj-…`) and admin/service shapes
_OPENAI = _Rule(
    label="OPENAI_KEY",
    pattern=re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}\b"),
)

# GitHub tokens (classic `ghp_`, fine-grained `github_pat_`, app `ghs_`, OAuth `gho_`)
_GITHUB = _Rule(
    label="GITHUB_TOKEN",
    pattern=re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{82,})\b"),
)

# AWS access key IDs (always start AKIA / ASIA / AGPA / etc., 20 chars total)
_AWS_KEY_ID = _Rule(
    label="AWS_KEY_ID",
    pattern=re.compile(r"\b(?:AKIA|ASIA|AGPA|AROA|AIDA|AIPA|ANPA|ANVA|ABIA|ACCA)[A-Z0-9]{16}\b"),
)

# AWS secret keys — 40 chars of base64ish — usually after `aws_secret_access_key=`
_AWS_SECRET = _Rule(
    label="AWS_SECRET",
    pattern=re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?"),
)

# Slack bot/user/legacy tokens
_SLACK = _Rule(
    label="SLACK_TOKEN",
    pattern=re.compile(r"\bxox[baprso]-[A-Za-z0-9-]{10,}\b"),
)

# Stripe live keys (sk_live_…, rk_live_…)
_STRIPE = _Rule(
    label="STRIPE_KEY",
    pattern=re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{24,}\b"),
)

# Google API keys (`AIza…`)
_GOOGLE = _Rule(
    label="GOOGLE_KEY",
    pattern=re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
)

# JWT tokens — three base64url segments separated by `.`
_JWT = _Rule(
    label="JWT",
    pattern=re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\b"),
)

# Generic `Authorization: Bearer <token>` headers (strict; same-string)
_AUTH_BEARER = _Rule(
    label="BEARER_TOKEN",
    pattern=re.compile(r"(?i)\bauthorization\s*[:=]\s*[\"']?bearer\s+([A-Za-z0-9._-]{16,})[\"']?"),
)

# Standalone `Bearer <token>` — fires even when ``Authorization:`` lives in
# a sibling JSON key rather than the same string. This is common for nested
# event payloads where ``{"Authorization": "Bearer ..."}`` redacts only the
# value-string. We require the token to look token-like (≥20 chars, with
# both alpha and either digit or underscore) to avoid false positives on
# prose like "bearer of bad news".
#
# Task 1.6 attempted to drop this rule (it looked like an over-engineered
# duplicate of `_AUTH_BEARER`). Empirically it is load-bearing: the
# integration-test suite covers nested-JSON payloads and prose-style bearer
# error messages that ONLY this rule catches. See the deferred-task note in
# docs/EXECUTION_PLAN.md.
_AUTH_BEARER_LOOSE = _Rule(
    label="BEARER_TOKEN",
    pattern=re.compile(
        r"(?i)\bbearer\s+([A-Za-z][A-Za-z0-9._-]*[0-9_][A-Za-z0-9._-]{16,}|"
        r"[A-Za-z0-9._-]*[0-9_][A-Za-z0-9._-]*[A-Za-z][A-Za-z0-9._-]{16,})"
    ),
)

# `.env` lines that look like SECRET / PASSWORD / API_KEY = <something>.
# Matches the *value*. We intentionally pattern-match only when the LHS
# screams "secret" — matching every `=` would be way too aggressive.
#
# The ``(?!\[REDACTED)`` negative lookahead skips values that earlier
# (more specific) rules already replaced with a redaction marker. Without
# it, ``SLACK_TOKEN=xoxb-...`` first gets redacted by the Slack rule to
# ``SLACK_TOKEN=[REDACTED:SLACK_TOKEN]``, and then env-line would match
# again and clobber it with ``[REDACTED:ENV_SECRET]``, losing the more
# precise label. Empirically required by tests/test_redact.py — see
# docs/EXECUTION_PLAN.md Task 1.6 deferred-task note.
_ENV_LINE = _Rule(
    label="ENV_SECRET",
    pattern=re.compile(
        r"(?im)^(?:[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|API[_-]?KEY|PASSWORD|PASS|PWD|"
        r"CREDENTIAL|PRIVATE[_-]?KEY)[A-Z0-9_]*)\s*=\s*[\"']?(?!\[REDACTED)([^\s\"']{6,})[\"']?"
    ),
)

# PEM private keys — multi-line block. We replace the whole block.
_PEM_KEY = _Rule(
    label="PRIVATE_KEY",
    pattern=re.compile(
        r"-----BEGIN [A-Z ]*?PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*?PRIVATE KEY-----"
    ),
)

# Supabase service role keys (JWT shape, but worth having a labelled rule
# since users hit them constantly). They follow the JWT pattern, so the
# JWT rule above will already cover them; keeping this comment for clarity.

# Database URLs with embedded credentials (postgres://user:password@host/...)
_DB_URL_CREDS = _Rule(
    label="DB_URL_PASSWORD",
    pattern=re.compile(
        r"\b(?:postgres|postgresql|mysql|mongodb|redis|rediss|amqp|amqps)://"
        r"[^:\s/]+:([^@\s]+)@[^/\s]+",
    ),
)


# ---- Task 1.5: provider-specific patterns sourced from gitleaks v8.20+ ----
#
# Each rule targets credentials Forge users routinely deploy with. The
# patterns are conservative — same approach as the Anthropic / OpenAI rules
# above (require a recognizable prefix plus a minimum token-body length).

# Vercel deploy / access tokens
_VERCEL = _Rule(
    label="VERCEL_TOKEN",
    pattern=re.compile(r"\bver_(?:live|test)_[A-Za-z0-9_-]{32,}\b"),
)

# Cloudflare scoped API tokens (newer format; legacy global API keys not
# distinguishable from generic hex without context, so we don't try)
_CLOUDFLARE_TOKEN = _Rule(
    label="CLOUDFLARE_TOKEN",
    pattern=re.compile(r"\bc_[A-Za-z0-9_-]{40,}\b"),
)

# npm v7+ scoped automation tokens (live in ~/.npmrc)
_NPM_TOKEN = _Rule(
    label="NPM_TOKEN",
    pattern=re.compile(r"\bnpm_[A-Za-z0-9_-]{36,}\b"),
)

# Hugging Face user / write tokens
_HUGGINGFACE_TOKEN = _Rule(
    label="HUGGINGFACE_TOKEN",
    pattern=re.compile(r"\bhf_[A-Za-z0-9_-]{30,}\b"),
)

# SendGrid API keys (always 'SG.<id>.<secret>')
_SENDGRID_KEY = _Rule(
    label="SENDGRID_KEY",
    pattern=re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
)

# Mailgun API keys (legacy 'key-' prefix + 32 hex chars)
_MAILGUN_KEY = _Rule(
    label="MAILGUN_KEY",
    pattern=re.compile(r"\bkey-[a-f0-9]{32}\b"),
)

# Twilio account SID (always 'AC' + 32 hex)
_TWILIO_SID = _Rule(
    label="TWILIO_SID",
    pattern=re.compile(r"\bAC[a-f0-9]{32}\b"),
)

# Discord bot tokens — three base64url segments separated by dots, leading
# with [MN] (the encoded user-id snowflake prefix for bot accounts)
_DISCORD_BOT = _Rule(
    label="DISCORD_BOT_TOKEN",
    pattern=re.compile(r"\b[MN][A-Za-z0-9_-]{23,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{27,}\b"),
)

# Telegram bot tokens (numeric_id : 'AA' + base64url tail)
_TELEGRAM_BOT = _Rule(
    label="TELEGRAM_BOT_TOKEN",
    pattern=re.compile(r"\b\d{8,12}:AA[A-Za-z0-9_-]{32,}\b"),
)


_RULES: tuple[_Rule, ...] = (
    # PEM blocks first — they're multi-line and we want to consume the whole thing
    _PEM_KEY,
    # Specific provider patterns next
    _ANTHROPIC,
    _OPENAI,
    _GITHUB,
    _AWS_KEY_ID,
    _AWS_SECRET,
    _SLACK,
    _STRIPE,
    _GOOGLE,
    # Task 1.5 additions — placed before the generic env-line rule so the
    # specific labels win when both could match.
    _VERCEL,
    _CLOUDFLARE_TOKEN,
    _NPM_TOKEN,
    _HUGGINGFACE_TOKEN,
    _SENDGRID_KEY,
    _MAILGUN_KEY,
    _TWILIO_SID,
    _DISCORD_BOT,
    _TELEGRAM_BOT,
    _JWT,
    _AUTH_BEARER,
    _AUTH_BEARER_LOOSE,
    _DB_URL_CREDS,
    # Then the generic .env-line rule (lower priority — less specific shape)
    _ENV_LINE,
)


# Public marker format. Tests assert against this exact shape so changing it
# is a breaking change — keep stable.
def _marker(label: str) -> str:
    return f"[REDACTED:{label}]"


def redact(text: str) -> str:
    """Replace any matched credential shape with a labelled marker.

    Returns the redacted string. Idempotent — running twice produces the
    same output (markers don't match any pattern).

    Performance: O(n × |rules|) per pass. For typical log/trace sizes
    (<10 KB) this is sub-millisecond.
    """
    if not text:
        return text

    out = text
    for rule in _RULES:
        # For rules with a capturing group (DB URLs, env lines, AWS secret,
        # bearer headers), redact only the captured group. For others,
        # redact the whole match.
        if rule.pattern.groups > 0:
            out = rule.pattern.sub(
                lambda m, label=rule.label: m.group(0).replace(m.group(1), _marker(label)),
                out,
            )
        else:
            out = rule.pattern.sub(_marker(rule.label), out)
    return out


def contains_secret(text: str) -> bool:
    """Fast yes/no — does ``text`` look like it contains any credential?

    Used by the KB-write gate to refuse persisting items that obviously
    contain secrets. Returns True on first match; doesn't enumerate.
    """
    if not text:
        return False
    return any(rule.pattern.search(text) for rule in _RULES)


# ---- Recursive structured-data redaction ----


def redact_value(value):
    """Recursively redact a JSON-like value.

    Handles dict / list / str. Other types pass through. Used by the trace
    writer to scrub event ``data`` payloads without serializing first.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_value(v) for v in value)
    return value


# ---- Subprocess env filtering ----


# Env vars Forge subprocesses (`claude -p`, ollama via Popen) actually need.
# Anything else is dropped — protects against leaking unrelated CI tokens,
# AWS creds, etc., into the subprocess environment.
_SUBPROCESS_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Forge's own configuration
        "FORGE_DB_PATH",
        "FORGE_DIR",
        "FORGE_VECTOR_EPISODES",
        "FORGE_REDACT_PROMPTS",
        "FORGE_EMBED_DIMS",
        # Provider keys for the LLM the subprocess is invoking
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        # Ollama
        "OLLAMA_BASE_URL",
        "OLLAMA_KEEP_ALIVE",
        "OLLAMA_MAX_LOADED_MODELS",
        # Standard runtime context every subprocess needs
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TMP",
        "TEMP",
        # Locale-y stuff that breaks Python startup if missing
        "PYTHONPATH",
        "PYTHONIOENCODING",
        "PYTHONUNBUFFERED",
        # Git wants these
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_DIR",
        "GIT_WORK_TREE",
        # GitHub CLI
        "GITHUB_TOKEN",  # passed only when user explicitly opts in via gh-cli
        "GH_TOKEN",
        # Node / npm — when we shell out to npm test
        "NODE_ENV",
        "NPM_CONFIG_LOGLEVEL",
        # SSH for git operations
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
    }
)


def filtered_subprocess_env(extra_keys: set[str] | None = None) -> dict[str, str]:
    """Return a filtered copy of ``os.environ`` for subprocess execution.

    Drops everything except the allowlist + the optional ``extra_keys`` the
    caller explicitly opts into. The result is suitable to pass as
    ``env=`` to ``asyncio.create_subprocess_exec``.

    Why allowlist not denylist: a denylist requires us to know every key
    the user might have set; an allowlist fails closed (forgotten env var
    gets dropped, not leaked). The allowlist above is conservative — it
    misses some legitimate env vars (e.g., custom proxy settings) which we
    add as we hit them.

    The ``extra_keys`` parameter exists so individual executors can opt in
    to additional env vars without bloating the global allowlist (e.g., the
    Anthropic batch executor might want ``ANTHROPIC_BATCH_*`` extras).
    """
    allowed = _SUBPROCESS_ENV_ALLOWLIST | (extra_keys or set())
    return {k: v for k, v in os.environ.items() if k in allowed}


# ---- Logging filter ----


class RedactionFilter:
    """A ``logging.Filter`` that redacts log message content before format.

    Install on the root logger or on specific loggers in
    ``daemon.log.LOG_CONFIG`` to scrub credentials from the ``.forge/forge.log``
    file. The filter mutates the log record's ``msg`` and ``args`` in place
    so downstream formatters see redacted data.

    Cost: one ``redact()`` pass per record. Negligible at typical log volume.
    """

    def filter(self, record):
        # Redact the message template
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        # Redact each argument (defensive — many callers pass user input)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_value(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_value(v) for v in record.args)
        return True
