"""Tests for daemon/redact.py — outbound credential redaction (ADR-017).

Each rule needs:
  - A positive test (does it match a real-shape credential?)
  - A negative test (does it NOT fire on plausible non-secrets?)
  - A redaction-output test (does the marker have the expected label?)

The pattern catalog is security-critical — false negatives leak; false
positives mangle user data. Both are real costs.
"""

from __future__ import annotations

import logging

from daemon.redact import (
    RedactionFilter,
    contains_secret,
    filtered_subprocess_env,
    redact,
    redact_value,
)

# ---- Anthropic ----


def test_anthropic_key_redacted():
    text = "key=sk-ant-api03-abc" + "x" * 90 + "_def"
    out = redact(text)
    assert "sk-ant-" not in out
    assert "[REDACTED:ANTHROPIC_KEY]" in out


def test_anthropic_short_string_not_redacted():
    """Short strings starting with sk-ant aren't real keys."""
    assert "sk-ant-" not in redact("not-a-real-key")
    # ``sk-ant-foo`` is too short for the rule's 80-char minimum
    assert redact("sk-ant-foo") == "sk-ant-foo"


# ---- OpenAI ----


def test_openai_legacy_key_redacted():
    text = "OPENAI_KEY=sk-" + "a" * 48
    out = redact(text)
    assert "sk-aaaa" not in out
    assert "[REDACTED:OPENAI_KEY]" in out


def test_openai_project_key_redacted():
    text = "key=sk-proj-" + "x" * 50
    out = redact(text)
    assert "sk-proj-xxxx" not in out
    assert "[REDACTED:OPENAI_KEY]" in out


def test_openai_service_account_key_redacted():
    text = "sk-svcacct-" + "y" * 40
    out = redact(text)
    assert "[REDACTED:OPENAI_KEY]" in out


# ---- GitHub ----


def test_github_classic_pat_redacted():
    text = "token=ghp_" + "A" * 40
    out = redact(text)
    assert "ghp_AAAA" not in out
    assert "[REDACTED:GITHUB_TOKEN]" in out


def test_github_fine_grained_pat_redacted():
    text = "token=github_pat_" + "1" * 90
    out = redact(text)
    assert "github_pat_" not in out
    assert "[REDACTED:GITHUB_TOKEN]" in out


# ---- AWS ----


def test_aws_access_key_id_redacted():
    text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    out = redact(text)
    assert "AKIA" not in out
    assert "[REDACTED:AWS_KEY_ID]" in out


def test_aws_secret_access_key_redacted_only_value():
    """Only the secret value is redacted; the variable name stays for context."""
    text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    out = redact(text)
    assert "wJalrXUtnFEMI" not in out
    assert "aws_secret_access_key=" in out
    assert "[REDACTED:AWS_SECRET]" in out


# ---- Slack ----


def test_slack_bot_token_redacted():
    text = "SLACK_TOKEN=xoxb-1234567890-abcdefghijklmnop"
    out = redact(text)
    assert "[REDACTED:SLACK_TOKEN]" in out


# ---- Stripe ----


def test_stripe_live_secret_key_redacted():
    text = "STRIPE_SECRET=sk_live_" + "x" * 40
    out = redact(text)
    assert "[REDACTED:STRIPE_KEY]" in out


def test_stripe_test_key_redacted():
    """Test keys are also secrets in our threat model."""
    text = "key=sk_test_" + "x" * 40
    out = redact(text)
    assert "[REDACTED:STRIPE_KEY]" in out


# ---- Google ----


def test_google_api_key_redacted():
    text = "GOOGLE_API_KEY=AIza" + "x" * 35
    out = redact(text)
    assert "[REDACTED:GOOGLE_KEY]" in out


# ---- JWT ----


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    text = f"Authorization: Bearer {jwt}"
    out = redact(text)
    assert "eyJhbGc" not in out
    # Either the JWT rule or the BEARER_TOKEN rule will fire — both are correct
    assert "REDACTED" in out


# ---- Authorization: Bearer ----


def test_bearer_header_redacted_value_only():
    text = "Authorization: Bearer abc123def456ghi789"
    out = redact(text)
    assert "abc123def456ghi789" not in out
    assert "Authorization" in out  # header name preserved
    assert "[REDACTED:BEARER_TOKEN]" in out


# ---- DB URL ----


def test_postgres_url_password_redacted():
    text = "DATABASE_URL=postgres://admin:supersecret123@db.host.com/mydb"
    out = redact(text)
    assert "supersecret123" not in out
    assert "admin:" in out  # username preserved
    assert "[REDACTED:DB_URL_PASSWORD]" in out


def test_redis_url_password_redacted():
    text = "redis://user:pass@redis.host:6379/0"
    out = redact(text)
    assert "pass@" not in out
    assert "[REDACTED:DB_URL_PASSWORD]" in out


# ---- .env-line patterns ----


def test_env_secret_line_redacted():
    text = "MY_API_KEY=abcdef123456"
    out = redact(text)
    assert "abcdef123456" not in out
    assert "MY_API_KEY=" in out
    assert "[REDACTED:ENV_SECRET]" in out


def test_env_token_line_redacted():
    text = "DEPLOY_TOKEN=ghp_dummytoken1234567890abcdef"
    out = redact(text)
    # GitHub rule will fire first (more specific)
    assert "ghp_dummytoken1234567890abcdef" not in out
    assert "REDACTED" in out


def test_env_password_line_redacted():
    text = "DB_PASSWORD=p@ssw0rd!"
    out = redact(text)
    assert "p@ssw0rd!" not in out


def test_env_unrelated_var_not_redacted():
    """Don't redact NODE_ENV=production etc. — they're not secrets."""
    assert redact("NODE_ENV=production") == "NODE_ENV=production"
    assert redact("PORT=3000") == "PORT=3000"


# ---- PEM keys ----


def test_pem_rsa_private_key_redacted():
    text = """before
-----BEGIN RSA PRIVATE KEY-----
MIIEogIBAAKCAQEA0vG6F8X9...
abc...
-----END RSA PRIVATE KEY-----
after"""
    out = redact(text)
    assert "MIIEogIBAAKCAQEA" not in out
    assert "before" in out
    assert "after" in out
    assert "[REDACTED:PRIVATE_KEY]" in out


def test_pem_ec_private_key_redacted():
    text = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIA\n-----END EC PRIVATE KEY-----"
    out = redact(text)
    assert "[REDACTED:PRIVATE_KEY]" in out


# ---- Negative cases (don't fire) ----


def test_safe_text_unchanged():
    assert redact("just normal text") == "just normal text"


def test_url_without_password_not_redacted():
    text = "https://example.com/path"
    assert redact(text) == text


def test_short_hex_not_redacted():
    """Short hex strings are not flagged — too many false positives."""
    text = "color: #abc123"
    assert redact(text) == text


def test_empty_string():
    assert redact("") == ""


def test_redact_is_idempotent():
    """Running redact twice produces the same output (markers don't match patterns)."""
    text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    once = redact(text)
    twice = redact(once)
    assert once == twice


# ---- contains_secret ----


def test_contains_secret_true_on_anthropic_key():
    assert contains_secret("sk-ant-api03-" + "x" * 80) is True


def test_contains_secret_false_on_safe_text():
    assert contains_secret("hello world") is False


def test_contains_secret_handles_empty():
    assert contains_secret("") is False
    assert contains_secret(None) is False  # type: ignore[arg-type]


# ---- redact_value (recursive) ----


def test_redact_value_recurses_into_dict():
    data = {"key": "AKIAIOSFODNN7EXAMPLE", "ok": "fine"}
    out = redact_value(data)
    assert "AKIA" not in out["key"]
    assert out["ok"] == "fine"


def test_redact_value_recurses_into_list():
    data = ["fine", "AKIAIOSFODNN7EXAMPLE", "also-fine"]
    out = redact_value(data)
    assert out[0] == "fine"
    assert "AKIA" not in out[1]
    assert out[2] == "also-fine"


def test_redact_value_handles_nested():
    data = {
        "headers": {"Authorization": "Bearer abc123def456ghijklmn"},
        "body": ["stuff", {"token": "ghp_" + "a" * 40}],
    }
    out = redact_value(data)
    assert "abc123def456ghijklmn" not in out["headers"]["Authorization"]
    assert "ghp_aaaa" not in out["body"][1]["token"]


def test_redact_value_passes_through_non_strings():
    data = {"count": 42, "ratio": 3.14, "active": True, "items": None}
    out = redact_value(data)
    assert out == data


# ---- filtered_subprocess_env ----


def test_filtered_env_drops_unrelated_keys(monkeypatch):
    """Non-allowlisted env vars get dropped."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "shouldNotPropagate")
    monkeypatch.setenv("MY_CUSTOM_TOKEN", "shouldNotPropagate")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = filtered_subprocess_env()
    assert "ANTHROPIC_API_KEY" in env
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert "PATH" in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "MY_CUSTOM_TOKEN" not in env


def test_filtered_env_extra_keys_pass_through(monkeypatch):
    """Caller can opt in to additional keys."""
    monkeypatch.setenv("MY_CUSTOM_TOKEN", "value")
    env = filtered_subprocess_env(extra_keys={"MY_CUSTOM_TOKEN"})
    assert env["MY_CUSTOM_TOKEN"] == "value"


def test_filtered_env_includes_locale(monkeypatch):
    """Common runtime env vars stay (locale, HOME, etc.)."""
    monkeypatch.setenv("HOME", "/Users/test")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    env = filtered_subprocess_env()
    assert "HOME" in env
    assert "LANG" in env


# ---- RedactionFilter ----


def test_redaction_filter_scrubs_log_message(caplog):
    log = logging.getLogger("test_redact_filter")
    log.addFilter(RedactionFilter())
    log.setLevel(logging.WARNING)

    with caplog.at_level(logging.WARNING, logger="test_redact_filter"):
        # Build the test string outside the logger call so we don't trip
        # ruff G003 (logging-statement-uses-+); the redaction logic doesn't
        # care whether the secret arrived via concatenation or formatting.
        leaky_msg = "auth failed: ANTHROPIC_API_KEY=sk-ant-api03-" + "x" * 90
        log.warning(leaky_msg)

    # The captured record's message should be redacted
    assert any("[REDACTED:ANTHROPIC_KEY]" in r.getMessage() for r in caplog.records)
    assert not any("sk-ant-api03-xxxx" in r.getMessage() for r in caplog.records)


def test_redaction_filter_scrubs_log_args():
    """When loggers use %-formatting with args, redact those too."""
    log = logging.getLogger("test_redact_args")
    log.addFilter(RedactionFilter())

    record = logging.LogRecord(
        name="test_redact_args",
        level=logging.WARNING,
        pathname="x",
        lineno=1,
        msg="key was %s",
        args=("AKIAIOSFODNN7EXAMPLE",),
        exc_info=None,
    )
    f = RedactionFilter()
    f.filter(record)
    msg = record.getMessage()
    assert "AKIA" not in msg
    assert "[REDACTED:AWS_KEY_ID]" in msg


# ---- Task 1.5: provider-specific patterns from gitleaks v8.20+ ----


# Vercel


def test_vercel_live_token_redacted():
    text = "VERCEL_TOKEN=ver_live_" + "x" * 36
    out = redact(text)
    assert "ver_live_xxxx" not in out
    assert "[REDACTED:VERCEL_TOKEN]" in out


def test_vercel_short_string_not_redacted():
    assert redact("ver_live_short") == "ver_live_short"


# Cloudflare


def test_cloudflare_token_redacted():
    text = "CF_TOKEN=c_" + "x" * 45
    out = redact(text)
    assert "[REDACTED:CLOUDFLARE_TOKEN]" in out


# npm


def test_npm_token_redacted():
    text = "//registry.npmjs.org/:_authToken=npm_" + "y" * 40
    out = redact(text)
    assert "[REDACTED:NPM_TOKEN]" in out


# HuggingFace


def test_huggingface_token_redacted():
    text = "HF_TOKEN=hf_" + "z" * 35
    out = redact(text)
    assert "[REDACTED:HUGGINGFACE_TOKEN]" in out


# SendGrid


def test_sendgrid_key_redacted():
    text = "SENDGRID=SG." + "a" * 22 + "." + "b" * 43
    out = redact(text)
    assert "[REDACTED:SENDGRID_KEY]" in out


# Mailgun


def test_mailgun_key_redacted():
    text = "MAILGUN_KEY=key-0123456789abcdef0123456789abcdef"
    out = redact(text)
    assert "[REDACTED:MAILGUN_KEY]" in out


# Twilio


def test_twilio_sid_redacted():
    text = "TWILIO_SID=AC0123456789abcdef0123456789abcdef"
    out = redact(text)
    assert "[REDACTED:TWILIO_SID]" in out


# Discord


def test_discord_bot_token_redacted():
    # Discord bot tokens are three base64url segments separated by dots,
    # leading with [MN]. Lengths chosen to match the rule's minimums.
    text = "DISCORD=N" + "A" * 23 + ".XYZ123.abc" + "x" * 25
    out = redact(text)
    assert "[REDACTED:DISCORD_BOT_TOKEN]" in out


# Telegram


def test_telegram_bot_token_redacted():
    text = "TELEGRAM=123456789:AA" + "x" * 35
    out = redact(text)
    assert "[REDACTED:TELEGRAM_BOT_TOKEN]" in out


# ---- Task 4.3: adversarial inputs ----


def test_redact_handles_long_input_without_redos():
    """Pathological input (100k near-JWT chars) finishes in well under a
    practical timeout. Guards against any rule's regex slipping into
    catastrophic backtracking territory.
    """
    import time

    junk = "e" * 100_000 + "yJ"  # near-JWT trigger pattern
    start = time.time()
    redact(junk)
    elapsed = time.time() - start
    assert elapsed < 0.5, f"redact() took {elapsed:.2f}s on 100k input — possible ReDoS"


def test_redact_handles_long_repeated_bearer_input():
    """A long stream of repeated 'Bearer …' fragments shouldn't blow up the
    loose-bearer rule."""
    import time

    junk = " ".join(["Bearer abc123" for _ in range(5000)])
    start = time.time()
    redact(junk)
    elapsed = time.time() - start
    assert elapsed < 0.5, f"redact() took {elapsed:.2f}s — possible ReDoS"
