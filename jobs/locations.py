"""Conservative, offline Australian location parsing and per-location filtering.

Only public reference files beside this module are read. No database, network,
coordinates, metro inference or job-wide work-mode aggregation is involved.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).with_name("data")
_MODE = re.compile(r"\b(?:remote|hybrid|on[\s-]?site|work from home|wfh)\b", re.I)
_POSTCODE = re.compile(r"\b[0-9]{4}\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", text)).strip()


@lru_cache(maxsize=1)
def _reference():
    """Fail visibly on a broken installation, rather than silently hiding jobs."""
    metadata = json.loads((_DATA / "location-reference.json").read_text(encoding="utf-8"))
    data = (_DATA / "au-postcodes.tsv").read_bytes()
    if (metadata["schema_version"] != 1 or
            hashlib.sha256(data).hexdigest() != metadata["seed"]["sha256"]):
        raise ValueError("Australian location reference is invalid; restore the bundled data files.")
    places: dict[str, set[tuple[str, str, str]]] = {}
    postcodes: dict[str, set[tuple[str, str]]] = {}
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t")
    if reader.fieldnames != ["postcode", "locality", "state"]:
        raise ValueError("Australian location reference has invalid columns.")
    count = 0
    for row in reader:
        pc, name, state = row["postcode"], row["locality"], row["state"]
        if not re.fullmatch(r"[0-9]{4}", pc) or not name or state not in metadata["states"]:
            raise ValueError("Australian location reference has an invalid row.")
        places.setdefault(_norm(name), set()).add((pc, state, name))
        postcodes.setdefault(pc, set()).add((name, state))
        count += 1
    if count != metadata["seed"]["rows"] or not count:
        raise ValueError("Australian location reference has an invalid row count.")
    aliases = {_norm(code): code for code in metadata["states"]}
    aliases.update({_norm(name): code for code, name in metadata["states"].items()})
    cities = {_norm(name): (name, state) for name, state in metadata["cities"].items()}
    return metadata, places, postcodes, aliases, cities


def _mode(text: str) -> tuple[str, bool]:
    found = set()
    markers = list(_MODE.finditer(text))
    negated = False
    for match in markers:
        if re.search(r"\b(?:not|no|non)[\s-]+$", text[:match.start()], re.I):
            negated = True
            continue
        word = _norm(match.group())
        found.add("onsite" if word in ("onsite", "on site") else
                  "remote" if word in ("remote", "work from home", "wfh") else "hybrid")
    return (next(iter(found)) if len(found) == 1 and not negated else "unknown", bool(markers))


def _state_value(states: set[str]):
    return next(iter(states)) if len(states) == 1 else sorted(states)


def _generic_mode(work_type: str) -> str:
    mode, _ = _mode(work_type)
    # A work-type field containing its own location is not a generic fallback:
    # "Remote NSW" must not grant remote work to a Melbourne location.
    remainder = _norm(_MODE.sub(" ", work_type))
    remainder = re.sub(r"\b(?:full time|part time|fixed term|contract|casual|permanent|temporary|internship|fully)\b",
                       " ", remainder)
    return mode if not remainder.strip() else "unknown"


def _resolve(raw: str) -> dict:
    metadata, places, postcodes, aliases, cities = _reference()
    result = {"raw": raw, "precision": "unknown", "source": "GeoNames",
              "reference_version": metadata["reference_version"]}
    text = _norm(_MODE.sub(" ", raw))
    # Do not consume Australia inside South/Western Australia.
    country_pattern = r"(?<!south )(?<!western )\b(?:anywhere in |across )?australia(?: wide| only)?\b"
    country = bool(re.search(country_pattern, text))
    text = re.sub(country_pattern, " ", text)
    codes = set(_POSTCODE.findall(text))
    text = _norm(_POSTCODE.sub(" ", text))
    states: set[str] = set()
    # Consume edge qualifiers only, stopping at an actual place name. This
    # protects Victoria Park WA and South Australia from substring matches.
    while text:
        if text in aliases:
            states.add(aliases[text])
            text = ""
            break
        if text in places or text in cities:
            break
        ordered = sorted(aliases, key=len, reverse=True)
        suffix = next((alias for alias in ordered if text.endswith(" " + alias)), None)
        prefix = next((alias for alias in ordered if text.startswith(alias + " ")), None)
        if suffix:
            states.add(aliases[suffix])
            text = text[:-(len(suffix) + 1)].strip()
        elif prefix:
            states.add(aliases[prefix])
            text = text[len(prefix) + 1:].strip()
        else:
            break
    if states:
        result["state"] = _state_value(states)
    if len(states) > 1:
        return {**result, "reason": "conflicting_states"}
    state = next(iter(states), None)
    if len(codes) > 1:
        return {**result, "reason": "multiple_postcodes_unsplit"}
    if codes:
        pc = next(iter(codes))
        result["postcode"] = pc
        options = {(name, st) for name, st in postcodes.get(pc, ()) if not state or st == state}
        if not options:
            return {**result, "reason": "postcode_state_conflict" if pc in postcodes else "unsupported_postcode"}
        if text:
            named = {(name, st) for name, st in options if _norm(name) == text}
            if not named:
                return {**result, "reason": "postcode_locality_unverified"}
            options = named
            result["locality"] = sorted(options)[0][0]
        result["state"] = _state_value({st for _, st in options})
        return {**result, "precision": "postcode", "reason": "explicit_postcode"}
    if text in cities and (not state or state == cities[text][1]):
        name, st = cities[text]
        return {**result, "precision": "city", "city": name, "state": st,
                "reason": "city_not_cbd_postcode"}
    options = {(pc, st, name) for pc, st, name in places.get(text, ()) if not state or st == state}
    if len(options) == 1:
        pc, st, name = next(iter(options))
        return {**result, "precision": "locality", "locality": name, "postcode": pc,
                "state": st, "reason": "unique_locality"}
    if options:
        return {**result, "locality": sorted(options)[0][2],
                "state": _state_value({st for _, st, _ in options}), "reason": "ambiguous_locality"}
    if text in cities and state:
        return {**result, "reason": "city_state_conflict"}
    if text in places and state:
        return {**result, "reason": "locality_state_conflict"}
    if state:
        return {**result, "precision": "state",
                "reason": "unresolved_place_state_only" if text else "explicit_state"}
    if not text and country:
        return {**result, "precision": "country", "reason": "country_only"}
    return {**result, "reason": "not_in_reference"}


def _split(raw: str) -> list[str]:
    # Explicit alternatives, outside parentheses. Commas usually qualify a
    # locality (Richmond, VIC); split only when the next item starts a new place.
    chunks = []
    start = depth = 0
    separators = re.compile(r"[;/|\n]|\s+(?:and|&)\s+", re.I)
    for match in re.finditer(r"[()]|[;/|\n]|\s+(?:and|&)\s+", raw, re.I):
        token = match.group()
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif not depth and separators.fullmatch(token):
            chunks.append(raw[start:match.start()])
            start = match.end()
    chunks.append(raw[start:])
    result = []
    for chunk in chunks:
        current = ""
        current_start = 0
        for match in re.finditer(r"[^,]+", chunk):
            part = match.group().strip()
            if not part:
                continue
            if current:
                previous, following = _resolve(current), _resolve(part)
                kind = following["precision"]
                new_place = kind in ("city", "locality", "postcode") or following["reason"] == "ambiguous_locality"
                new_state = kind == "state" and previous["precision"] == "state"
                # A comma postcode following a city/locality is a qualifier.
                if kind == "postcode" and not _POSTCODE.search(current):
                    new_place = False
                previous_place = previous["precision"] != "unknown" or previous["reason"] == "ambiguous_locality"
                if (new_place or new_state) and previous_place:
                    result.append(current)
                    current = part
                    current_start = match.start()
                    continue
                current = chunk[current_start:match.end()].strip()
            else:
                current = part
                current_start = match.start()
        if current:
            result.append(current)
    return result


def parse_locations(raw: str | None, work_type: str | None = None) -> list[dict]:
    """Return separate conservative facts; work_type supplies only generic mode.

    Missing text produces one unknown location. Explicit per-location modes
    override the fallback, including conflicting/negated modes (kept unknown).
    State is a code or a sorted list of possible codes, never a guessed prefix.
    """
    if raw is not None and not isinstance(raw, str):
        raise TypeError("Location must be text or None.")
    if work_type is not None and not isinstance(work_type, str):
        raise TypeError("Work type must be text or None.")
    fallback = _generic_mode(work_type or "")
    locations = []
    parts = _split(raw or "") or [raw or ""]
    if len(parts) == 1 and parts[0].strip() == (raw or "").strip():
        parts = [raw or ""]
    for part in parts:
        mode, explicit = _mode(part)
        location = _resolve(part)
        location["work_mode"] = mode if explicit else fallback
        if explicit and mode == "unknown":
            location["reason"] += ";work_mode_uncertain"
        locations.append(location)
    return locations


def parse_target(text: str) -> dict:
    """Accept one supported postcode/state/capital/unique locality or raise.

    Clear a filter by passing target=None to classify, not by parsing a blank.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Enter an Australian postcode, state, city or unique locality; clear the filter to show all.")
    parts = _split(text)
    if len(parts) != 1 or _mode(text)[1]:
        raise ValueError("Choose one Australian location; set the work mode separately.")
    result = _resolve(text)
    if result["precision"] in ("unknown", "country") or result["reason"] == "unresolved_place_state_only":
        if result["reason"] == "ambiguous_locality":
            raise ValueError("This locality is ambiguous; add a state or a postcode.")
        raise ValueError("Location is unsupported or conflicts with the Australian reference; use a valid postcode, state, city or unique locality.")
    return result


def _states(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    return set(value or ())


def _geography(location: dict, target: dict) -> str:
    if location.get("precision", "unknown") == "unknown":
        return "unknown"
    own, wanted = _states(location.get("state")), _states(target.get("state"))
    if own and wanted and own.isdisjoint(wanted):
        return "hidden"
    uncertain_state = bool(own and wanted and not own <= wanted)
    # Also accept A-style target dictionaries containing only geographic keys.
    precision = target.get("precision") or next(
        (field for field in ("postcode", "city", "locality", "state") if target.get(field)), None)
    if precision == "state":
        return "match" if own and not uncertain_state else "related"
    if precision == "city":
        if location.get("city"):
            if _norm(location["city"]) != _norm(target["city"]):
                return "hidden"
            return "related" if uncertain_state else "match"
        return "related"
    if precision in ("postcode", "locality"):
        if location.get("postcode") and target.get("postcode"):
            if location["postcode"] != target["postcode"]:
                return "hidden"
            if precision == "locality":
                if not location.get("locality"):
                    return "related"
                if _norm(location["locality"]) != _norm(target["locality"]):
                    return "hidden"
            return "related" if uncertain_state else "match"
        return "related"
    return "unknown"


def classify(location: dict, target: dict | None = None, work_mode: str = "any") -> str:
    """Classify ONE location as match/related/unknown/hidden (A semantics).

    Parent callers select matching locations before aggregating a job. A mode
    on another location cannot satisfy this location's geographic restriction.
    """
    if work_mode not in {"any", "remote", "hybrid", "onsite"}:
        raise ValueError("Work mode must be any, remote, hybrid or onsite.")
    kind = _geography(location, target) if target else "match"
    if work_mode != "any":
        own_mode = location.get("work_mode", "unknown")
        if own_mode not in (work_mode, "unknown"):
            return "hidden"
        if own_mode == "unknown" and kind == "match":
            return "related"
    return kind
