"""Caddy must refuse any request that did not come through the Bunny edge.

The apex pull zone stamps every origin pull with ``X-Origin-Auth`` set to
``ORIGIN_SHARED_SECRET`` (an Edge Rule), so a request without the right value
bypassed the edge cache and its rate limits, whatever ``Host`` it wears. The
``@unauthenticated`` matcher answers those with a 403. Two callers are exempt:
SvelteKit SSR's own API calls, which arrive on the loopback interface, and
Railway's health probe, identified by its ``Host`` and path together so that
the same path arriving under the public host (Bunny forwarding the uptime
monitor) still has to carry the secret and a drifted secret is visible.

Nothing about the gate is observable from the application, so these
assertions pin it. The sentinel-default form of the matcher is the subtle
one: Caddy substitutes ``{$VAR}`` into the raw file before parsing, so an
unset variable would leave ``header X-Origin-Auth`` with no value, which is
the "field exists" matcher, and the gate would admit anyone sending the
header with any value.
"""

from __future__ import annotations

import re

from django.conf import settings

SENTINEL_FORM = "{$ORIGIN_SHARED_SECRET:__origin_secret_unset__}"


def _caddyfile() -> str:
    return (settings.BASE_DIR.parent / "Caddyfile").read_text()


def _gate_block() -> str:
    match = re.search(
        r"^@unauthenticated \{\n(.*?)^\}", _caddyfile(), re.MULTILINE | re.DOTALL
    )
    assert match, "Caddyfile must define an @unauthenticated matcher block"
    return match.group(1)


def _handle_position(name: str) -> int:
    position = _caddyfile().find(f"handle {name} {{")
    assert position != -1, f"Caddyfile must define a handle {name}"
    return position


def test_gate_compares_the_secret_with_the_sentinel_default() -> None:
    assert re.search(
        rf"^\s*not header X-Origin-Auth {re.escape(SENTINEL_FORM)}\s*$",
        _gate_block(),
        re.MULTILINE,
    ), (
        "@unauthenticated must negate `header X-Origin-Auth "
        f"{SENTINEL_FORM}`: without the sentinel default an unset variable "
        "leaves a bare `header X-Origin-Auth`, which matches any value"
    )


def test_gate_uses_the_same_expression_as_trusted_cdn() -> None:
    match = re.search(
        r"^@trusted_cdn header X-Origin-Auth (\S+)\s*$", _caddyfile(), re.MULTILINE
    )
    assert match, "Caddyfile must define @trusted_cdn on X-Origin-Auth"
    assert match.group(1) == SENTINEL_FORM, (
        "@trusted_cdn and @unauthenticated must compare the same expression, so "
        "a request the gate admits is one whose X-Client-IP is promoted"
    )


def test_gate_exempts_loopback_for_ssr() -> None:
    assert re.search(
        r"^\s*not remote_ip 127\.0\.0\.1 ::1\s*$", _gate_block(), re.MULTILINE
    ), (
        "@unauthenticated must exempt the loopback peer: SvelteKit SSR reaches "
        "/api/ through this listener without X-Origin-Auth"
    )


def test_gate_exempts_railways_health_probe_by_host_and_path_together() -> None:
    match = re.search(
        r"^\s*not \{\n(.*?)^\s*\}", _gate_block(), re.MULTILINE | re.DOTALL
    )
    assert match, (
        "@unauthenticated must exempt Railway's health probe in one `not { }` "
        "block: the probe carries no X-Origin-Auth, and a rejected probe blocks "
        "every deploy"
    )
    conditions = sorted(
        line.strip() for line in match.group(1).splitlines() if line.strip()
    )
    assert conditions == ["host healthcheck.railway.app", "path /__health"], (
        "the probe exemption must pair Railway's Host with the path, so a "
        "/__health request under the public host (the uptime monitor through "
        "Bunny) still needs the secret and a drifted secret turns the monitor "
        f"red; got {conditions}"
    )


def test_gate_does_not_exempt_the_health_path_on_its_own() -> None:
    assert not re.search(r"^\s*not path /__health\s*$", _gate_block(), re.MULTILINE), (
        "a bare `not path /__health` would exempt the uptime monitor's request "
        "too, hiding a drifted secret behind a green health check"
    )


def test_gate_has_no_other_exemptions() -> None:
    top_level = [
        line.strip()
        for line in _gate_block().splitlines()
        if line.strip() and line.strip() != "}" and not line.startswith("\t\t")
    ]
    assert len(top_level) == 3, (
        "@unauthenticated should carry exactly the secret check, the loopback "
        f"exemption and the health-probe block, got {top_level}"
    )


def test_rejected_requests_get_a_403() -> None:
    assert re.search(
        r"^handle @unauthenticated \{\n\s*respond 403\s*\n\}",
        _caddyfile(),
        re.MULTILINE,
    ), "handle @unauthenticated must answer with a bare 403"


def test_the_rejection_is_not_cacheable() -> None:
    match = re.search(
        r'^header\s+@unauthenticated\s+>Cache-Control\s+"([^"]+)"\s*$',
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, (
        "Caddyfile must set Cache-Control on the @unauthenticated matcher in the "
        "deferred `>` form: a plain set is overwritten by the deferred per-path "
        "policy, so a 403 on a font URL would leave with a one-year TTL"
    )
    assert "no-store" in match.group(1), (
        "a 403 from a drifted secret must not outlive the repair in any cache, "
        f"got {match.group(1)!r}"
    )


def test_handles_run_in_the_documented_order() -> None:
    direct = _handle_position("@direct_origin")
    gate = _handle_position("@unauthenticated")
    django = _handle_position("@django")
    assert direct < gate, (
        "handle @direct_origin must precede handle @unauthenticated: a crawler "
        "on the Railway hostname legitimately lacks the secret, and Caddy runs "
        "only the first matching handle"
    )
    assert gate < django, (
        "handle @unauthenticated must precede handle @django, or the gate is "
        "decorative for every /api/ and /djadmin/ request"
    )
