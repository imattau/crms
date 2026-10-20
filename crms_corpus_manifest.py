"""Validation and summaries for the CRMS corpus manifest.

The manifest is a planning inventory, not proof that a source has been acquired
or cleared. Validation enforces the schema and the licence/tier rules that make
the inventory useful before importers are written.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from typing import Any, Mapping

FORMAT = "crms-corpus-manifest"
VERSION = 1
TIERS = ("core", "extended", "research")
DOMAINS = (
    "reference", "general", "code", "math", "science",
    "books", "docs", "qa", "translation", "dialogue",
)
LICENCE_CLASSES = (
    "public-domain", "permissive", "share-alike",
    "copyleft", "restricted", "unknown",
)
STATUSES = ("candidate", "approved", "restricted")
CONFIDENCE = ("low", "medium", "high")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read corpus manifest: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("corpus manifest must be a JSON object")
    return payload


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_manifest(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    if payload.get("format") != FORMAT:
        errors.append(f"format must be {FORMAT!r}")
    try:
        version = int(payload.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != VERSION:
        errors.append(f"version must be {VERSION}")
    generated = str(payload.get("generated", ""))
    try:
        date.fromisoformat(generated)
    except ValueError:
        errors.append("generated must be an ISO date (YYYY-MM-DD)")

    tiers = payload.get("tiers")
    if not isinstance(tiers, dict):
        errors.append("tiers must be an object")
        tiers = {}
    for tier in TIERS:
        detail = tiers.get(tier)
        if not isinstance(detail, dict):
            errors.append(f"missing tier: {tier}")
            continue
        if not isinstance(detail.get("packaged"), bool):
            errors.append(f"tier {tier!r} needs a boolean packaged flag")
        if not _nonempty(detail.get("word_target")):
            errors.append(f"tier {tier!r} needs a word_target")
        if not _nonempty(detail.get("purpose")):
            errors.append(f"tier {tier!r} needs a purpose")

    targets = payload.get("domain_targets")
    if not isinstance(targets, dict):
        errors.append("domain_targets must be an object")
        targets = {}
    unknown_targets = set(targets) - set(DOMAINS)
    if unknown_targets:
        errors.append(f"unknown domain targets: {sorted(unknown_targets)}")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
           for value in targets.values()):
        errors.append("domain targets must be non-negative integers")
    elif sum(targets.values()) != 100:
        errors.append("domain targets must sum to 100")

    policy = payload.get("licence_policy")
    if not isinstance(policy, dict):
        errors.append("licence_policy must be an object")
    else:
        allowed = policy.get("core_allowed_classes", [])
        if not isinstance(allowed, list) or not allowed:
            errors.append("core_allowed_classes must be a non-empty list")
        elif set(allowed) - set(LICENCE_CLASSES):
            errors.append("core_allowed_classes contains an unknown class")
        if "unknown" in allowed:
            errors.append("unknown licences cannot be allowed in the core")
        if not isinstance(policy.get("core_requires_attribution"), bool):
            errors.append("core_requires_attribution must be a boolean")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    seen_ids: set[str] = set()
    core_words = 0
    for index, source in enumerate(sources):
        where = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{where} must be an object")
            continue
        source_id = str(source.get("id", ""))
        if not _ID.fullmatch(source_id):
            errors.append(f"{where} has an invalid id: {source_id!r}")
        if source_id in seen_ids:
            errors.append(f"duplicate source id: {source_id!r}")
        seen_ids.add(source_id)
        if not _nonempty(source.get("title")):
            errors.append(f"{where} needs a title")
        tier = source.get("tier")
        if tier not in TIERS:
            errors.append(f"{where} has an unknown tier: {tier!r}")
        domains = source.get("domains")
        if (not isinstance(domains, list) or not domains
                or any(domain not in DOMAINS for domain in domains)
                or len(set(domains)) != len(domains)):
            errors.append(f"{where} has invalid domains")
        formats = source.get("formats")
        if (not isinstance(formats, list) or not formats
                or any(not _nonempty(item) for item in formats)):
            errors.append(f"{where} has invalid formats")
        if not _nonempty(source.get("licence")):
            errors.append(f"{where} needs a licence")
        licence_class = source.get("licence_class")
        if licence_class not in LICENCE_CLASSES:
            errors.append(f"{where} has an unknown licence_class")
        if licence_class == "unknown":
            errors.append(f"{where} uses an unknown licence; move it to excluded")
        if not isinstance(source.get("attribution_required"), bool):
            errors.append(f"{where} needs attribution_required as a boolean")
        packaged_ok = source.get("packaged_ok")
        if not isinstance(packaged_ok, bool):
            errors.append(f"{where} needs packaged_ok as a boolean")
        status = source.get("status")
        if status not in STATUSES:
            errors.append(f"{where} has an unknown status")
        words = source.get("estimated_words")
        if words is not None and (
                not isinstance(words, int) or isinstance(words, bool) or words < 0):
            errors.append(f"{where} has an invalid estimated_words")
        if tier == "core":
            if packaged_ok is not True:
                errors.append(f"{where} is core but not packaged_ok")
            if status == "restricted":
                errors.append(f"{where} is core but restricted")
            if not isinstance(words, int) or isinstance(words, bool):
                errors.append(f"{where} is core but has no word estimate")
            else:
                core_words += words
        elif packaged_ok is True:
            errors.append(f"{where} is {tier} but marked packaged_ok")
        if source.get("estimate_confidence") not in CONFIDENCE:
            errors.append(f"{where} has an unknown estimate_confidence")
        for field in ("estimate_basis", "retrieval", "notes"):
            if not _nonempty(source.get(field)):
                errors.append(f"{where} needs {field}")
        if status in {"candidate", "approved"}:
            if not _nonempty(source.get("url")):
                errors.append(f"{where} needs a url")
            if not _nonempty(source.get("licence_url")):
                errors.append(f"{where} needs a licence_url")

    excluded = payload.get("excluded")
    if not isinstance(excluded, list):
        errors.append("excluded must be a list")
        excluded = []
    excluded_ids: set[str] = set()
    for index, item in enumerate(excluded):
        where = f"excluded[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        item_id = str(item.get("id", ""))
        if not _ID.fullmatch(item_id):
            errors.append(f"{where} has an invalid id: {item_id!r}")
        if item_id in excluded_ids:
            errors.append(f"duplicate excluded id: {item_id!r}")
        if item_id in seen_ids:
            errors.append(f"{item_id!r} appears in both sources and excluded")
        excluded_ids.add(item_id)
        if not _nonempty(item.get("title")):
            errors.append(f"{where} needs a title")
        if not _nonempty(item.get("reason")):
            errors.append(f"{where} needs a reason")
        if not _nonempty(item.get("licence_status")):
            errors.append(f"{where} needs a licence_status")

    return errors


def summarize_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    sources = [source for source in payload.get("sources", ())
               if isinstance(source, dict)]
    by_tier: dict[str, dict[str, Any]] = {}
    by_domain: dict[str, int] = {domain: 0 for domain in DOMAINS}
    by_licence: dict[str, int] = {}
    by_status: dict[str, int] = {}
    core_words = 0
    for source in sources:
        tier = str(source.get("tier", ""))
        record = by_tier.setdefault(tier, {
            "sources": 0, "known_words": 0, "unknown_estimates": 0,
        })
        record["sources"] += 1
        words = source.get("estimated_words")
        if isinstance(words, int) and not isinstance(words, bool):
            record["known_words"] += words
            if tier == "core":
                core_words += words
        else:
            record["unknown_estimates"] += 1
        for domain in source.get("domains", ()):
            if domain in by_domain:
                by_domain[domain] += 1
        licence = str(source.get("licence_class", ""))
        by_licence[licence] = by_licence.get(licence, 0) + 1
        status = str(source.get("status", ""))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total_sources": len(sources),
        "excluded_sources": len(payload.get("excluded", ())),
        "core_estimated_words": core_words,
        "by_tier": by_tier,
        "by_domain": by_domain,
        "by_licence_class": dict(sorted(by_licence.items())),
        "by_status": dict(sorted(by_status.items())),
        "domain_targets": dict(payload.get("domain_targets", {})),
    }
