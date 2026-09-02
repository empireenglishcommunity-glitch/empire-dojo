#!/usr/bin/env python3
"""Single source of truth for the facts that appear in the guide pages.

WHY THIS EXISTS
---------------
site/guide/index.html (student manual) and site/ops-guide/index.html (owner
manual) are the whole reference for students and the owner, and they MUST stay
accurate. They used to be hand-authored top to bottom, so every time the system
changed a fact drifted — e.g. the student guide claimed "~340 words" for A1 while
config says the A1 vocab_target is 750, and the ops-guide's feature-flag catalog
was missing entire initiatives (IJTIHAD, SUSPENSION, the assessment watchdog) and
still listed MI'YAR, which was retired.

This module reads the REAL system data — nothing hand-typed — and returns it as a
structured dict. Two consumers use it:
  * scripts/guide_sync.py fills the AUTO-marked regions in the two guide pages.
  * scripts/verify_guides.py fails CI when a hand-written fact in the guides no
    longer matches what this module reports.

SOURCES (all authoritative, all in empire-nexus except the surface list):
  * config.CEFR_LEVELS ............ levels, week counts, vocab targets, advancement
  * data/*.json .................... the ACTUAL distinct vocabulary count per level
  * flag_registry.REGISTRY ......... every feature flag + its default state
  * config schedule constants ...... DAILY_TASK_HOUR, WEEKLY_ASSESSMENT_HOUR, TIMEZONE
  * database.ITQAN_CONFIG_DEFAULTS . itqan thresholds (read as text; DB may override)
  * api_server task_types .......... the practice/exercise surfaces

Everything here is DERIVABLE and safe to regenerate. Editorial prose (how a
feature is explained, rights/privacy wording, tone) is NOT here and must stay
hand-written in the pages.
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
# Same convention generate.py uses: empire-nexus is a sibling, overridable.
EEC_REPO_DIR = Path(os.environ.get("EEC_REPO_DIR", REPO_ROOT.parent / "empire-nexus"))
BOT_DIR = EEC_REPO_DIR / "bots" / "discord-learning-bot"
BOT_SRC = BOT_DIR / "src"
DATA_DIR = BOT_DIR / "data"


class FactsUnavailable(RuntimeError):
    """empire-nexus is not present, so facts cannot be derived. Callers decide
    whether that is fatal (the sync/verify steps) or skippable."""


def _require_nexus():
    if not BOT_SRC.exists():
        raise FactsUnavailable(
            f"curriculum source not found at {BOT_SRC}. Clone empire-nexus as a "
            f"sibling of empire-dojo, or set EEC_REPO_DIR.")


def _ensure_dotenv_stub():
    """empire-nexus's config.py does `from dotenv import load_dotenv; load_dotenv()`
    at import. The dojo CI environment installs only its own deps (not the bot's),
    so python-dotenv is absent and importing config would ModuleNotFoundError —
    which silently left the guides UNSYNCED in CI. load_dotenv() is a no-op here
    (there is no .env to read), so provide a harmless stub when the real package
    is missing. This keeps guide_facts dependency-free, like generate.py."""
    if "dotenv" in sys.modules:
        return
    try:
        import dotenv  # noqa: F401
    except ImportError:
        import types
        stub = types.ModuleType("dotenv")
        stub.load_dotenv = lambda *a, **k: False
        sys.modules["dotenv"] = stub


def _import_bot_module(name):
    """Import a bot src module (config, flag_registry). config needs a dotenv
    shim (see _ensure_dotenv_stub); flag_registry imports cleanly. Neither
    touches the DB at import."""
    _ensure_dotenv_stub()
    if str(BOT_SRC) not in sys.path:
        sys.path.insert(0, str(BOT_SRC))
    return __import__(name)


# ── Levels ────────────────────────────────────────────────────────────────
def levels():
    """Per-level structural facts, straight from config.CEFR_LEVELS."""
    _require_nexus()
    config = _import_bot_module("config")
    out = []
    for code in config.CEFR_ORDER:
        lv = config.CEFR_LEVELS[code]
        out.append({
            "code": code,
            "title": lv["title"],            # CEFR band name, e.g. "Breakthrough"
            "name": lv["name"],              # e.g. "Beginner"
            "name_ar": lv["name_ar"],
            "emoji": lv["emoji"],
            "weeks": lv["weeks"],
            "vocab_target": lv["vocab_target"],
            "advancement_score": lv["advancement_score"],
        })
    return out


# ── Actual vocabulary count per level (from the authored data files) ────────
def vocab_counts():
    """DISTINCT vocabulary words actually authored per level, and the total.

    This is the real number behind claims like "first ~340 words" — measured,
    not asserted. Counts distinct `word`s across each level's week files.
    """
    _require_nexus()
    per_level, seen_global = {}, set()
    for f in sorted(glob.glob(str(DATA_DIR / "*.json"))):
        base = os.path.basename(f)
        m = re.match(r"([a-c][12])_week\d+\.json$", base)
        if not m:
            continue
        code = m.group(1).upper()
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        words = per_level.setdefault(code, set())
        for v in (d.get("vocabulary") or []):
            w = (v.get("word") or "").strip()
            if w:
                words.add(w.lower())
                seen_global.add(w.lower())
    counts = {code: len(words) for code, words in per_level.items()}
    counts["_total"] = len(seen_global)
    return counts


# ── Feature flags ───────────────────────────────────────────────────────────
def feature_flags():
    """Every flag grouped by initiative, with display metadata and default.

    Returns [{key, emoji, name, purpose, flags:[{name, description, default}]}]
    in a stable order (by first appearance in the REGISTRY).
    """
    _require_nexus()
    fr = _import_bot_module("flag_registry")
    order, groups = [], {}
    for name, desc, initiative, default in fr.REGISTRY:
        if initiative not in groups:
            order.append(initiative)
            groups[initiative] = []
        groups[initiative].append(
            {"name": name, "description": desc, "default": bool(default)})
    out = []
    for init in order:
        # Some initiatives in REGISTRY have no INITIATIVES metadata yet
        # (e.g. assessment, suspension, ijtihad as of 2026-09). Fall back to a
        # clean uppercased label + a neutral emoji so the guide never renders a
        # blank header — rather than silently dropping real, active flags.
        meta = fr.INITIATIVES.get(init)
        if meta:
            emoji, name, purpose = meta
        else:
            emoji, name, purpose = "🏳️", init.upper(), ""
        out.append({
            "key": init, "emoji": emoji, "name": name, "purpose": purpose,
            "flags": groups[init],
        })
    return out


# ── Schedule / timezone (authoritative constants) ───────────────────────────
def schedule():
    _require_nexus()
    config = _import_bot_module("config")
    return {
        "timezone": getattr(config, "TIMEZONE", "Asia/Dubai"),
        "daily_task_hour": getattr(config, "DAILY_TASK_HOUR", 6),
        "weekly_assessment_hour": getattr(config, "WEEKLY_ASSESSMENT_HOUR", 10),
    }


# ── Itqan thresholds (code DEFAULTS; live DB may override — verify warns) ────
def itqan_defaults():
    """Read ITQAN_CONFIG_DEFAULTS from database.py as TEXT (importing database
    needs a live DB). These are code defaults; the running system can override
    them, so the drift-check treats a mismatch here as a WARNING, not a failure."""
    _require_nexus()
    txt = (BOT_SRC / "database.py").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"ITQAN_CONFIG_DEFAULTS\s*=\s*\{(.*?)\}", txt, re.S)
    if not m:
        return {}
    out = {}
    for km in re.finditer(r'"([a-z_]+)"\s*:\s*([0-9.]+)', m.group(1)):
        val = km.group(2)
        out[km.group(1)] = float(val) if "." in val else int(val)
    return out


# ── Practice / exercise surfaces ─────────────────────────────────────────────
def surfaces():
    """The task/exercise types the system recognises, from the bot's API server
    (its own list, so it cannot drift from what the backend accepts)."""
    _require_nexus()
    txt = (BOT_SRC / "api_server.py").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"valid_types\s*=\s*\[([^\]]+)\]", txt)
    if not m:
        return []
    return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]


def all_facts():
    """The full structured fact set. Raises FactsUnavailable if nexus is absent."""
    lv = levels()
    vc = vocab_counts()
    return {
        "levels": lv,
        "level_count": len(lv),
        "total_weeks": sum(x["weeks"] for x in lv),
        "vocab_counts": vc,
        "feature_flags": feature_flags(),
        "flag_total": sum(len(g["flags"]) for g in feature_flags()),
        "schedule": schedule(),
        "itqan_defaults": itqan_defaults(),
        "surfaces": surfaces(),
    }


if __name__ == "__main__":
    facts = all_facts()
    print(json.dumps(facts, ensure_ascii=False, indent=2))
