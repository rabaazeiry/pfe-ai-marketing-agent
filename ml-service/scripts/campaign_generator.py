"""campaign_generator.py — Step 5 Campaign Generator (hybrid template + LLM).

Design (LOCKED — see audit + plan):
  - Python TEMPLATE owns every fact, number, date, hashtag, @handle,
    format and theme. The LLM produces ONLY French creative prose and
    is forbidden from emitting digits / '#' / '@' / English. There is
    nothing factual for the model to get wrong — facts never enter its
    output, only its context.
  - The 4-week dated calendar is anchored to the FIRST 4 weeks of the
    Prophet forecast. Each Prophet `week` value is the start of a
    7-day placement window [week, week+6]. Each week inherits its
    Prophet `intensity`; posts/week = Prophet `posts_recommended`
    (high->6 / normal->3 / low->1).
  - Day/time/format/theme/hashtag rotation re-anchors the proven
    deterministic logic of compute_facts.py:_build_calendar_30d onto
    the Prophet weeks (it is NOT reinvented).
  - One LLM call per post returns all 5 creative fields together
    (caption, hook, ad_angle, production_guide, visual_recommendation)
    so they stay mutually coherent; +1 call per campaign for the
    campaign_summary.

Inputs  : data/prophet/<ind>_forecast_v3.json   (forecast[0:4])
          data/step4f_v6/facts/facts_<ind>.json (deterministic facts)
Output  : data/step5/campaigns/campaign_<ind>.json

Usage:
    cd ml-service
    .venv/Scripts/python.exe -X utf8 scripts/campaign_generator.py --industry beauty
    .venv/Scripts/python.exe -X utf8 scripts/campaign_generator.py --industry all
    # structural-only (no Ollama, instant — verifies template + dates):
    .venv/Scripts/python.exe -X utf8 scripts/campaign_generator.py --industry beauty --no-llm
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
sys.stdout.reconfigure(encoding="utf-8")

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parents[1]
PROPHET_DIR  = ROOT / "data" / "prophet"
FACTS_DIR    = ROOT / "data" / "step4f_v6" / "facts"
OUT_DIR      = ROOT / "data" / "step5" / "campaigns"

INDUSTRIES    = ["beauty", "fashion", "hotels", "patisserie", "restaurants"]
FIRST_N_WEEKS = 4                       # locked: first 4 Prophet weeks
DAY_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

# ── LLM config (same construction convention as rephrase_facts.py) ────────────
LLM_MODEL   = "llama3.1:latest"
TEMPERATURE = 0.4                       # creative copy needs variety (vs 0.0 rephraser)
NUM_CTX     = 4096
NUM_PREDICT = 700
TIMEOUT_S   = 180
MAX_RETRIES = 1                         # one repair retry, then deterministic fallback


# ═══════════════════════════════════════════════════════════════════════════════
#  LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

def load_prophet(industry: str) -> Optional[List[Dict[str, Any]]]:
    p = PROPHET_DIR / f"{industry}_forecast_v3.json"
    if not p.exists():
        print(f"  [{industry}] {p.name} missing — run prophet_train.py first")
        return None
    fc = json.loads(p.read_text(encoding="utf-8")).get("forecast", [])
    if len(fc) < FIRST_N_WEEKS:
        print(f"  [{industry}] forecast has {len(fc)} weeks (<{FIRST_N_WEEKS})")
        return None
    return fc[:FIRST_N_WEEKS]


def load_facts(industry: str) -> Optional[Dict[str, Any]]:
    p = FACTS_DIR / f"facts_{industry}.json"
    if not p.exists():
        print(f"  [{industry}] {p.name} missing — run compute_facts.py first")
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
#  CLIENT-SAFETY FILTERS  (FIX 1–4: competitor brands · seasonal · meta)
# ═══════════════════════════════════════════════════════════════════════════════
#
# facts_<ind>.json themes/hashtags are derived from SCRAPED COMPETITOR posts
# (Step 3). Surfacing them verbatim makes the client's own campaign promote
# its competitors. We therefore (a) strip competitor-brand / out-of-season
# themes from the pools and the LLM grounding, (b) replace hashtags with a
# fixed generic Tunisian sector pool, and (c) make the prose validator reject
# any competitor brand name or chatbot/meta phrasing the LLM might echo.

# (FIX 2 / ADJ 3) Fixed generic Tunisian hashtag pool — replaces competitor
# @handles. ~12 per industry so 30 posts don't repeat the same 3-4 tags.
_GENERIC_HASHTAGS: Dict[str, List[str]] = {
    "beauty": ["#beautetunisie", "#soinsvisage", "#routinebeaute",
               "#soinsnaturels", "#maquillage", "#peausaine", "#cosmetiques",
               "#astucesbeaute", "#beauteautrement", "#tunisie",
               "#beautyblogger", "#tunisienne"],
    "fashion": ["#modetunisie", "#styletunisien", "#tendancemode",
                "#lookdujour", "#inspirationmode", "#ootd", "#fashiontunisia",
                "#modefemme", "#stylish", "#tunisie", "#shoppingtunisie",
                "#tendance"],
    "hotels": ["#hoteltunisie", "#tourismetunisie", "#vacancestunisie",
               "#voyagetunisie", "#sejour", "#escapade", "#destinationtunisie",
               "#traveltunisia", "#detente", "#tunisie", "#weekend",
               "#hospitalite"],
    "patisserie": ["#patisserietunisie", "#gourmandise", "#dessert",
                   "#douceurs", "#patisseriemaison", "#gateau", "#sucre",
                   "#faitmaison", "#gourmand", "#tunisie", "#patisserie",
                   "#foodtunisia"],
    "restaurants": ["#restauranttunisie", "#cuisinetunisienne", "#foodtunisia",
                    "#restotunis", "#cuisinelocale", "#goodfood", "#saveurs",
                    "#foodlover", "#gastronomie", "#tunisie", "#restaurant",
                    "#miam"],
}

# (FIX 1 / ADJ 2) Generic per-industry themes. ALWAYS appended to the filtered
# real themes (not just a last-resort fallback) so every industry has enough
# variety for a 30-day calendar.
_GENERIC_THEMES: Dict[str, List[str]] = {
    "beauty": ["Routine beauté", "Soins du visage", "Conseils beauté",
               "Astuces maquillage", "Peau saine", "Beauté naturelle"],
    "fashion": ["Inspiration mode", "Style du quotidien", "Tendances mode",
                "Look du jour", "Conseils style", "Mode tunisienne"],
    "hotels": ["Évasion et séjour", "Expérience hôtelière",
               "Découverte tourisme", "Détente et bien-être",
               "Escapade locale", "Art de recevoir"],
    "patisserie": ["Douceurs gourmandes", "Création pâtissière",
                   "Plaisir sucré", "Pâtisserie maison", "Recette du jour",
                   "Gourmandise tunisienne"],
    "restaurants": ["Cuisine du jour", "Saveurs locales", "Expérience gourmande",
                    "Plat signature", "Convivialité à table",
                    "Cuisine tunisienne"],
}

# (FIX 1 / FIX 4) Known competitor brands seen in the scraped Step-3 data
# (theme slugs + @handles). Matched whole-token so e.g. "turki" never hits
# "Turkish". Extend this list as new competitors are scraped.
_KNOWN_BRANDS: List[str] = [
    # fashion
    "zara", "bershka", "pull&bear", "pull and bear", "pullandbear", "kastelo",
    # hotels
    "hilton", "el mouradi", "elmouradi", "mouradi", "el mouradi palace",
    # restaurants
    "papa john", "papa johns", "kfc", "le golfe", "the 716",
    # patisserie
    "maison turki", "turki",
    # beauty
    "bioderma", "nuxe", "lella", "sephora", "veryrose",
]
_BRAND_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(b) for b in _KNOWN_BRANDS) + r")(?!\w)",
    re.IGNORECASE)

# Theme tokens that promote *other* businesses rather than the client's sector.
_COMPETITOR_KW_RE = re.compile(r"\breviews?\b", re.IGNORECASE)
# English possessive ("Papa John's …") — strong brand signal in a theme slug.
_POSSESSIVE_RE = re.compile(r"\b[\wÀ-ÿ]+'s\b", re.IGNORECASE)
# "&"-joined brand token ("Pull&Bear") — generic sector themes never use it.
_AMP_BRAND_RE = re.compile(r"\w&\w")
# (ADJ 1) BERTopic clustering artifacts — meaningless as marketing themes
# ("Outliers (mixed content)", "Multi-Industry Lifestyle", …).
_JUNK_THEME_RE = re.compile(
    r"\b(?:outliers?|mixed content|multi[- ]industry|cross[- ]industry)\b",
    re.IGNORECASE)

# (FIX 4) Chatbot / meta phrasing the LLM sometimes leaks into prose
# (e.g. the hotels campaign_summary: "Je suis prêt à continuer si vous…").
_META_PHRASES: List[str] = [
    "je suis prêt", "je suis pret",
    "si vous souhaitez", "souhaitez-vous que je",
    "je peux développer", "je peux developper", "je peux continuer",
    "n'hésitez pas à me demander", "n'hesitez pas a me demander",
    "n'hésitez pas à me ", "n'hesitez pas a me ",
    "je reste à votre disposition", "je reste a votre disposition",
    "voici le résumé", "voici le resume", "comme demandé", "comme demande",
]

# (FIX 3) Seasonal windows in 2026, ordered specific→generic. A theme that
# mentions a season is KEPT only if that season overlaps the campaign window.
# NOTE: generic "eid"/"aïd" maps to Eid al-Adha (26–30 May 2026), so for a
# May–June window Eid themes are IN-SEASON and kept (not blindly excluded).
def _d(month: int, day: int) -> datetime:
    return datetime(2026, month, day)

_SEASON_RULES: List[Tuple[Any, List[Tuple[datetime, datetime]]]] = [
    (re.compile(r"\bramadan\b", re.I),                              [(_d(2, 17), _d(3, 21))]),
    (re.compile(r"\b(?:eid[ -]?al[- ]?fitr|a[iï]d[ -]?el[- ]?fitr|fitr)\b", re.I),
                                                                    [(_d(3, 20), _d(3, 23))]),
    (re.compile(r"\b(?:valentine'?s?|valentin)\b", re.I),           [(_d(2, 13), _d(2, 15))]),
    (re.compile(r"\b(?:no[eë]l|christmas|hiver|winter)\b", re.I),
                                       [(_d(1, 1), _d(2, 28)), (_d(12, 1), _d(12, 31))]),
    (re.compile(r"\b(?:eid[ -]?al[- ]?adha|al[- ]?adha|adha|idha|k[eé]bir|sacrifice)\b", re.I),
                                                                    [(_d(5, 26), _d(5, 30))]),
    (re.compile(r"\b(?:eid|a[iï]d)\b", re.I),                       [(_d(5, 26), _d(5, 30))]),
    (re.compile(r"\b(?:summer|[ée]t[ée]|estival)\b", re.I),         [(_d(6, 1), _d(8, 31))]),
]


def _overlap(lo: datetime, hi: datetime, wlo: datetime, whi: datetime) -> bool:
    return lo <= whi and wlo <= hi


def _theme_in_season(name: str, wlo: datetime, whi: datetime) -> bool:
    """KEEP a theme that mentions a season only if that 2026 season overlaps
    the campaign window. Themes with no seasonal keyword are always kept."""
    for rx, ranges in _SEASON_RULES:
        if rx.search(name):
            return any(_overlap(lo, hi, wlo, whi) for lo, hi in ranges)
    return True


def _theme_has_brand(name: str) -> bool:
    """A theme is competitor-tainted if it names a known brand, uses an
    English possessive / '&'-brand token, or promotes competitor 'reviews'."""
    return bool(_BRAND_RE.search(name) or _POSSESSIVE_RE.search(name)
                or _AMP_BRAND_RE.search(name) or _COMPETITOR_KW_RE.search(name))


def _theme_is_junk(name: str) -> bool:
    """A theme is a meaningless BERTopic artifact (outliers / mixed content /
    multi-/cross-industry) — useless to a client, dropped like brand themes."""
    return bool(_JUNK_THEME_RE.search(name))


def _theme_is_client_safe(name: str, wlo: datetime, whi: datetime) -> bool:
    return (bool(name) and _theme_in_season(name, wlo, whi)
            and not _theme_has_brand(name) and not _theme_is_junk(name))


# ═══════════════════════════════════════════════════════════════════════════════
#  TEMPLATE LAYER — structure from Prophet + facts (zero LLM)
# ═══════════════════════════════════════════════════════════════════════════════

def build_pools(industry: str, facts: Dict[str, Any],
                win_lo: datetime, win_hi: datetime) -> Dict[str, Any]:
    """Build the rotation pools, mirroring compute_facts.py:_build_calendar_30d.
    Themes are then stripped of competitor brands / out-of-season seasons
    (FIX 1+3) and hashtags are replaced by a fixed generic pool (FIX 2)."""
    m       = facts.get("modules", {})
    timing  = m.get("optimal_timing", {})
    visual  = m.get("visual_strategy", {})
    themesb = m.get("content_themes", {})
    # NOTE: m["hashtag_strategy"] is intentionally NOT used — those tags are
    # competitor @handles (FIX 2 replaces them with _GENERIC_HASHTAGS).

    best_day_dows = [d.get("dow") for d in (timing.get("best_days") or [])
                     if d.get("dow") is not None]
    if not best_day_dows:
        best_day_dows = list(range(7))

    hour_pool = [h.get("hour_tunis") for h in (timing.get("best_hours") or [])
                 if h.get("hour_tunis") is not None]

    formats = [f["content_type"] for f in (visual.get("format_performance") or [])
               if f.get("content_type")] or ["photo", "reel", "carousel"]

    # Theme pool: interleave volume + performance themes, own-industry only
    # (topic_id -1 = neutral "Outliers", None = generic fallback are allowed —
    # same allowed set as compute_facts' Step A.4 guard).
    themes_pool: List[Dict[str, Any]] = []
    seen = set()
    for src in (themesb.get("top_5_by_share", []), themesb.get("top_5_by_er", [])):
        for t in src or []:
            name = (t or {}).get("topic_name")
            if not name or name in seen:
                continue
            if t.get("is_own_industry") or t.get("topic_id") in (-1, None):
                themes_pool.append({"topic_id": t.get("topic_id"), "topic_name": name})
                seen.add(name)
    # (FIX 1+3 / ADJ 1) Drop competitor-brand, out-of-season and BERTopic-junk
    # themes — the client must never promote a competitor, a finished season
    # or a meaningless clustering artifact.
    themes_pool = [t for t in themes_pool
                   if _theme_is_client_safe(t["topic_name"], win_lo, win_hi)]
    # (ADJ 2) ALWAYS enrich with generic sector themes (dedup by name), so
    # every industry has enough variety for a 30-day calendar even when the
    # filtered real-theme pool is small or empty.
    seen_names = {t["topic_name"] for t in themes_pool}
    for n in _GENERIC_THEMES.get(industry, ["contenu générique"]):
        if n not in seen_names:
            themes_pool.append({"topic_id": None, "topic_name": n})
            seen_names.add(n)

    # (FIX 2) Generic Tunisian sector hashtags — never competitor @handles.
    hashtags_pool = list(_GENERIC_HASHTAGS.get(industry, ["#tunisie"]))

    return {
        "best_day_dows": best_day_dows,
        "hour_pool":     hour_pool,
        "formats":       formats,
        "themes_pool":   themes_pool,
        "hashtags_pool": hashtags_pool,
    }


def place_week_posts(week_start: datetime, p: int,
                     best_day_dows: List[int]) -> List[Tuple[str, str]]:
    """Return p (date_iso, day_fr) tuples inside [week_start, week_start+6],
    one per distinct weekday, best-days first then the rest of the window,
    sorted chronologically. p<=6 and the window has 7 distinct weekdays so
    distinct dates are always available (no collisions)."""
    base_wd = week_start.weekday()                        # Monday=0 .. Sunday=6
    chosen: List[int] = []
    for t in best_day_dows:                               # primary: best days
        if len(chosen) >= p:
            break
        if t not in chosen:
            chosen.append(t)
    if len(chosen) < p:                                   # fill from window order
        for off in range(7):
            if len(chosen) >= p:
                break
            t = (base_wd + off) % 7
            if t not in chosen:
                chosen.append(t)
    dates = []
    for t in chosen[:p]:
        off = (t - base_wd) % 7                            # unique offset 0..6
        d = week_start + timedelta(days=off)
        dates.append(d)
    dates.sort()
    return [(d.strftime("%Y-%m-%d"), DAY_FR[d.weekday()]) for d in dates]


def build_skeleton(industry: str, forecast: List[Dict[str, Any]],
                    facts: Dict[str, Any], pools: Dict[str, Any]) -> Dict[str, Any]:
    """Build the full §6b structure with all deterministic fields filled and
    the 5 creative text fields left as None (filled by the LLM layer)."""
    fmts   = pools["formats"]
    themes = pools["themes_pool"]
    htags  = pools["hashtags_pool"]
    hours  = pools["hour_pool"]
    anchor = forecast[0]["week"]

    weeks: List[Dict[str, Any]] = []
    k = 0                                                  # global rotation counter
    for w_idx, w in enumerate(forecast, 1):
        wk_start = datetime.strptime(w["week"], "%Y-%m-%d")
        p        = int(w["posts_recommended"])
        placed   = place_week_posts(wk_start, p, pools["best_day_dows"])

        posts = []
        for p_idx, (date_iso, day_fr) in enumerate(placed, 1):
            theme = themes[k % len(themes)]
            fmt   = fmts[k % len(fmts)]
            if htags:
                s = (k * 3) % len(htags)
                tags = [htags[(s + j) % len(htags)] for j in range(min(3, len(htags)))]
            else:
                tags = []
            best_time = f"{hours[k % len(hours)]}h" if hours else ""
            posts.append({
                "post_index":            p_idx,
                "date":                  date_iso,
                "day_of_week":           day_fr,
                "best_time":             best_time,
                "format":                fmt,
                "theme":                 theme["topic_name"],
                "hashtags":              tags,
                "_k":                    k,        # transient rotation seed
                "caption":               None,
                "hook":                  None,
                "ad_angle":              None,
                "production_guide":      None,
                "visual_recommendation": None,
                "status":                "PENDING",
            })
            k += 1

        weeks.append({
            "week_index":           w_idx,
            "week_start":           w["week"],
            "intensity":            w["intensity"],
            "predicted_engagement": round(float(w["predicted_engagement"]), 4),
            "posts_recommended":    p,
            "posts":                posts,
        })

    return {
        "version":      "campaign_v1",
        "industry":     industry,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "model":        LLM_MODEL,
        "sources": {
            "prophet": f"{industry}_forecast_v3.json",
            "facts":   f"facts_{industry}.json",
        },
        "anchor_week": anchor,
        "campaign_summary": {
            "title":           None,
            "objective":       None,
            "target_audience": None,
            "platforms":       ["instagram"],          # template-owned, fixed
        },
        "weeks": weeks,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  GROUNDING — qualitative cues only (NO numbers reach the LLM)
# ═══════════════════════════════════════════════════════════════════════════════

_LEN_FR = {"q1_shortest": "très courte", "q2": "courte",
           "q3": "moyenne", "q4_longest": "longue"}

# French sector labels (the facts `industry` key is an English slug).
_IND_FR = {"beauty": "beauté", "fashion": "mode", "hotels": "hôtellerie",
           "patisserie": "pâtisserie", "restaurants": "restauration"}


def _det(sector: str, form: str = "la") -> str:
    """French definite article with correct elision (vowel / h muet).
    'hôtellerie' is h muet -> l'hôtellerie, de l'hôtellerie, par l'hôtellerie."""
    elide = sector[:1].lower() in "aeiouàâäéèêëîïôöùûh"
    if form == "de":
        return f"de l'{sector}" if elide else f"de la {sector}"
    if form == "par":
        return f"par l'{sector}" if elide else f"par la {sector}"
    if form == "La":                                   # sentence-initial
        return f"L'{sector}" if elide else f"La {sector}"
    return f"l'{sector}" if elide else f"la {sector}"


def build_grounding(industry: str, facts: Dict[str, Any],
                    win_lo: datetime, win_hi: datetime) -> Dict[str, Any]:
    """Turn the relevant facts numbers into QUALITATIVE French instructions.
    The model never sees a single digit — only directions like
    'évite les mots promotionnels'. This makes numeric hallucination
    structurally impossible in the creative fields."""
    m  = facts.get("modules", {})
    cs = m.get("content_strategy", {})
    et = m.get("engagement_tactics", {})
    ct = m.get("content_themes", {})
    tr = m.get("current_trends", {})
    bd = m.get("brand_differentiation", {})

    # Best caption-length bucket (max median_er)
    quart = cs.get("caption_length_quartiles") or []
    best_len = max(quart, key=lambda q: q.get("median_er", -1), default=None)
    caption_len = _LEN_FR.get((best_len or {}).get("bucket", ""), "courte")

    # Tone from sentiment share (qualitative)
    sent = cs.get("sentiment", {})
    pos  = sent.get("positive_share", 0) or 0
    neg  = sent.get("negative_share", 0) or 0
    tone = "résolument positif" if pos >= max(neg, 1) * 3 else "équilibré"

    # Signal directions (sign only -> do / don't)
    do, dont = [], []
    for t in (et.get("tactic_lifts") or []):
        d = t.get("er_delta", 0) or 0
        name = {"cta": "un appel à l'action insistant",
                "question": "une question ouverte",
                "promo_word": "des mots promotionnels"}.get(t.get("tactic"), t.get("tactic"))
        (do if d > 0 else dont).append(name)
    for s in (cs.get("binary_signal_lifts") or []):
        if s.get("signal") == "has_emoji":
            (do if (s.get("er_delta", 0) or 0) > 0 else dont).append(
                "une profusion d'emojis")

    # Rising own-industry theme + an underserved theme (names only)
    emerging = next((e.get("topic_name") for e in (tr.get("emerging_themes") or [])
                     if e.get("is_own_industry")
                     and (e.get("share_delta_pp", 0) or 0) > 0), None)
    underserved = next((u.get("topic_name")
                        for u in (bd.get("underserved_themes") or [])), None)
    top_share = next((t.get("topic_name")
                      for t in (ct.get("top_5_by_share") or [])
                      if t.get("is_own_industry")), None)

    # (FIX 1/3) Never feed a competitor-brand or out-of-season theme name into
    # the LLM context — otherwise it echoes them into captions / ad_angles.
    def _safe(n: Optional[str]) -> Optional[str]:
        return n if (n and _theme_is_client_safe(n, win_lo, win_hi)) else None
    emerging    = _safe(emerging)
    underserved = _safe(underserved)
    top_share   = _safe(top_share)

    # Ordered, distinct angle pool — rotated per post so the ad_angle is not
    # fixated on a single (possibly out-of-season) trend campaign-wide.
    angle_pool: List[str] = []
    for a in (emerging, underserved, top_share):
        if a and a not in angle_pool:
            angle_pool.append(a)

    return {
        "caption_len":  caption_len,
        "tone":         tone,
        "do":           [x for x in do if x],
        "dont":         [x for x in dont if x],
        "emerging":     emerging,
        "underserved":  underserved,
        "top_share":    top_share,
        "angle_pool":   angle_pool,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM LAYER
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu es un copywriter marketing tunisien. On te donne un CONTEXTE FIXE \
(date, jour, heure, format, thème, hashtags) DÉJÀ décidé : tu ne le répètes pas, \
tu ne le contredis pas, tu écris autour de lui.

TU PRODUIS UNIQUEMENT DU TEXTE CRÉATIF EN FRANÇAIS.

INTERDICTIONS ABSOLUES — toute infraction invalide ta réponse :
- AUCUN chiffre, AUCUN pourcentage, AUCUNE date écrite en chiffres.
- AUCUN caractère « # » ni « @ », AUCUN hashtag, AUCun identifiant de compte.
- AUCUN mot anglais. AUCUN nom de marque, AUCUNE collaboration/partenariat inventé.
- AUCUN format ni canal absent du contexte (pas de « live », « story » si absent).

Respecte EXACTEMENT ce gabarit, en-têtes compris, rien avant ni après :

CAPTION :
[la légende, longueur demandée, ton demandé, sans chiffre ni hashtag]
HOOK :
[une accroche pour les 3 premières secondes]
ANGLE :
[une phrase : l'angle marketing / positionnement]
PRODUCTION :
[instructions concrètes de tournage/prise de vue pour ce format]
VISUEL :
[description de l'image idéale — du texte descriptif, PAS une consigne de génération d'image]"""

_POST_USER_TMPL = """SECTEUR : {industry}

CONTEXTE FIXE (ne pas répéter, ne pas contredire) :
- Jour de publication : {day}
- Heure : {time}
- Format : {fmt}
- Thème : {theme}
- Hashtags déjà choisis (NE PAS les réécrire toi-même) : {tags}

CONSIGNES CRÉATIVES :
- Longueur de la légende : {clen}
- Ton : {tone}
{do}{dont}- Angle : t'appuyer sur la dynamique « {angle_theme} » (sans inventer de chiffre).
- PRODUCTION : instructions adaptées au format « {fmt} »{carousel}.
- VISUEL : décrire une image {tone}, nette, soignée, cohérente avec « {theme} », pensée pour Instagram.

Rédige les 5 sections en suivant le gabarit imposé."""

_SUMMARY_USER_TMPL = """SECTEUR : {industry}

Rédige le résumé d'une campagne Instagram de 4 semaines pour ce secteur, en français,
SANS aucun chiffre, hashtag, « @ », mot anglais ni marque inventée.
Appuie-toi sur le thème porteur « {top}{emerging}{underserved} ».

Respecte EXACTEMENT ce gabarit :

TITRE :
[titre court et accrocheur de la campagne]
OBJECTIF :
[objectif marketing en une à deux phrases]
AUDIENCE :
[description de l'audience cible]"""


def _fmt_list(label: str, items: List[str]) -> str:
    return f"- {label} : {', '.join(items)}.\n" if items else ""


def build_post_prompt(industry: str, post: Dict[str, Any],
                      g: Dict[str, Any]) -> str:
    pool = g.get("angle_pool") or []
    angle_theme = (pool[post.get("_k", 0) % len(pool)] if pool
                   else post["theme"])
    carousel = (" (plusieurs diapositives, progression claire)"
                if post["format"] == "carousel" else "")
    user = _POST_USER_TMPL.format(
        industry=industry,
        day=post["day_of_week"],
        time=post["best_time"] or "non précisée",
        fmt=post["format"],
        theme=post["theme"],
        tags=", ".join(post["hashtags"]) if post["hashtags"] else "aucun",
        clen=g["caption_len"],
        tone=g["tone"],
        do=_fmt_list("Tu peux utiliser", g["do"]),
        dont=_fmt_list("À éviter absolument", g["dont"]),
        angle_theme=angle_theme,
        carousel=carousel,
    )
    return f"{SYSTEM_PROMPT}\n\n{user}"


def build_summary_prompt(industry: str, g: Dict[str, Any]) -> str:
    top = g["top_share"] or "le secteur"
    emerging = f" » et la tendance « {g['emerging']}" if g["emerging"] else ""
    underserved = (f" » et l'opportunité « {g['underserved']}"
                   if g["underserved"] else "")
    return _SUMMARY_USER_TMPL.format(
        industry=industry, top=top, emerging=emerging, underserved=underserved)


# ── Parsing ───────────────────────────────────────────────────────────────────

_POST_KEYS = {"CAPTION": "caption", "HOOK": "hook", "ANGLE": "ad_angle",
              "PRODUCTION": "production_guide", "VISUEL": "visual_recommendation"}
_SUM_KEYS  = {"TITRE": "title", "OBJECTIF": "objective", "AUDIENCE": "target_audience"}


def _split_sections(text: str, headers: List[str]) -> Dict[str, str]:
    """Tolerant section split (markdown-bold / missing colon / column-0)."""
    pat = r'(?:^|\n)\s*[*#]*\s*(' + "|".join(headers) + r')\s*:?\s*[*#]*\s*\n?'
    parts = re.split(pat, text)
    out: Dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i]] = re.sub(r"\*+", "", parts[i + 1]).strip()
    return out


def parse_post(text: str) -> Optional[Dict[str, str]]:
    secs = _split_sections(text, list(_POST_KEYS))
    fields = {dst: secs.get(src, "").strip() for src, dst in _POST_KEYS.items()}
    if any(len(v) < 8 for v in fields.values()):           # a section missing/empty
        return None
    return fields


def parse_summary(text: str) -> Optional[Dict[str, str]]:
    secs = _split_sections(text, list(_SUM_KEYS))
    fields = {dst: secs.get(src, "").strip() for src, dst in _SUM_KEYS.items()}
    if any(len(v) < 5 for v in fields.values()):
        return None
    return fields


# ── Validator: the LLM must emit NO digit / # / @ / English ───────────────────

# Only words that are essentially never valid French (so we don't falsely
# reject FR copy that legitimately uses "image", "audience", "engagement",
# "post", which are also French words).
_EN_MARKERS = re.compile(
    r"\b(the|and|with|your|content|brand|strategy|week|best|"
    r"awareness|reach|insights)\b", re.IGNORECASE)


def validate_prose(text: str) -> List[str]:
    """Return a list of French violation messages (empty = clean)."""
    bad: List[str] = []
    if re.search(r"\d", text):
        bad.append("contient un chiffre (interdit — aucun nombre autorisé)")
    if "#" in text:
        bad.append("contient « # » ou un hashtag (interdit)")
    if "@" in text:
        bad.append("contient « @ » (interdit)")
    if len(_EN_MARKERS.findall(text)) >= 2:
        bad.append("contient des mots anglais (réponse 100% française exigée)")
    # (FIX 4) Block competitor brand names (conservative whole-token list —
    # no possessive/'&' heuristic here, to avoid French false positives).
    if _BRAND_RE.search(text):
        bad.append("contient un nom de marque concurrente (interdit)")
    # (FIX 4) Block chatbot / meta phrasing addressed to the operator.
    tl = text.lower()
    if any(p in tl for p in _META_PHRASES):
        bad.append("contient une formulation méta/chatbot (interdite)")
    return bad


def _repair_suffix(violations: List[str]) -> str:
    return ("\n\n──────────\nCORRECTION OBLIGATOIRE. Ta réponse précédente "
            "violait des règles ABSOLUES :\n- "
            + "\n- ".join(violations)
            + "\nRéécris INTÉGRALEMENT en respectant le gabarit EXACT et "
              "SANS aucun chiffre, hashtag, « @ », mot anglais, nom de marque "
              "ni formulation méta/chatbot (écris UNIQUEMENT le contenu "
              "marketing demandé, sans t'adresser à l'utilisateur).")


# ── Deterministic fallback (template-owned, trusted, never validated) ─────────

def fallback_post(industry: str, post: Dict[str, Any],
                  g: Dict[str, Any]) -> Dict[str, str]:
    """Deterministic, hallucination-safe French copy used when the LLM is
    unreachable or its output fails validation/parsing twice. Reads like
    real (if generic) marketing copy — never a spec — and never quotes the
    English theme slug, contains no number / # / @ / English."""
    sector = _IND_FR.get(industry, industry)
    fmt    = post["format"]
    tone_adj = "positif et chaleureux" if "positif" in g["tone"] else "sincère"
    # Rotate variants so repeated fallbacks within a campaign differ.
    idx = (post.get("post_index", 1) + len(fmt)) % 3
    captions = [
        f"Prendre soin de chaque détail, c'est ça l'esprit {sector}.",
        f"{_det(sector, 'La')} qui nous ressemble, jour après jour.",
        f"Un instant {tone_adj} à partager autour {_det(sector, 'de')}.",
    ]
    hooks = [
        "Et si on s'accordait un vrai moment rien que pour soi ?",
        "Voici le détail qui change tout au quotidien.",
        "Ce qu'on attendait pour sublimer cette saison, le voici.",
    ]
    fmt_guide = {
        "reel":     ("Tourner une courte vidéo verticale dynamique : plan "
                     "d'ouverture fort, enchaînement rythmé, lumière soignée, "
                     "message clair en fin de séquence."),
        "carousel": ("Préparer plusieurs visuels cohérents en progression : "
                     "première image accrocheuse, développement clair, visuel "
                     "de conclusion incitatif."),
        "photo":    ("Composer une photographie soignée et lumineuse : sujet "
                     "centré, arrière-plan épuré, cadrage net."),
    }.get(fmt, "Soigner le cadrage, la lumière et la lisibilité du message.")
    return {
        "caption":  captions[idx],
        "hook":     hooks[idx],
        "ad_angle": (f"Mettre en avant une {sector} authentique et accessible, "
                     f"en phase avec les attentes actuelles du public tunisien."),
        "production_guide": fmt_guide,
        "visual_recommendation": (f"Image lumineuse et soignée, cadrage net et "
                                  f"épuré pensé pour Instagram, fidèle à "
                                  f"l'univers {_det(sector, 'de')}."),
    }


def fallback_summary(industry: str, g: Dict[str, Any]) -> Dict[str, str]:
    sector = _IND_FR.get(industry, industry)
    return {
        "title": f"Campagne {sector} — quatre semaines d'engagement",
        "objective": ("Renforcer la notoriété et l'engagement de la marque sur "
                      "Instagram pendant quatre semaines, autour d'un contenu "
                      "régulier, soigné et cohérent."),
        "target_audience": (f"Public tunisien intéressé {_det(sector, 'par')} et "
                            f"attentif aux tendances actuelles du secteur."),
    }


# ── One generation with 1 retry then deterministic fallback ──────────────────

def generate_post(llm, industry: str, post: Dict[str, Any],
                   g: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
    """Returns (fields, status) with status OK / REPAIRED / FALLBACK."""
    prompt = build_post_prompt(industry, post, g)
    try:
        resp = llm.invoke(prompt)
    except Exception as e:                                  # Ollama unreachable
        return fallback_post(industry, post, g), f"FALLBACK(llm_error:{type(e).__name__})"

    parsed = parse_post(resp)
    violations = validate_prose(resp) if parsed else ["format de sortie invalide"]
    if parsed and not violations:
        return parsed, "OK"

    for _ in range(MAX_RETRIES):                            # one repair attempt
        try:
            resp_r = llm.invoke(prompt + _repair_suffix(violations))
        except Exception:
            break
        parsed_r = parse_post(resp_r)
        viol_r = validate_prose(resp_r) if parsed_r else ["format invalide"]
        if parsed_r and not viol_r:
            return parsed_r, "REPAIRED"
    return fallback_post(industry, post, g), "FALLBACK"


def generate_summary(llm, industry: str, g: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
    prompt = f"{SYSTEM_PROMPT}\n\n{build_summary_prompt(industry, g)}"
    try:
        resp = llm.invoke(prompt)
    except Exception as e:
        return fallback_summary(industry, g), f"FALLBACK(llm_error:{type(e).__name__})"
    parsed = parse_summary(resp)
    violations = validate_prose(resp) if parsed else ["format invalide"]
    if parsed and not violations:
        return parsed, "OK"
    for _ in range(MAX_RETRIES):
        try:
            resp_r = llm.invoke(prompt + _repair_suffix(violations))
        except Exception:
            break
        parsed_r = parse_summary(resp_r)
        viol_r = validate_prose(resp_r) if parsed_r else ["format invalide"]
        if parsed_r and not viol_r:
            return parsed_r, "REPAIRED"
    return fallback_summary(industry, g), "FALLBACK"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCHEMA VALIDATION (build-order (a)/(b) — runs every time, before write)
# ═══════════════════════════════════════════════════════════════════════════════

def validate_schema(c: Dict[str, Any]) -> None:
    assert c["version"] == "campaign_v1"
    assert c["industry"] in INDUSTRIES
    assert c["campaign_summary"]["platforms"] == ["instagram"]
    assert len(c["weeks"]) == FIRST_N_WEEKS, "must cover exactly 4 Prophet weeks"
    for w in c["weeks"]:
        ws = datetime.strptime(w["week_start"], "%Y-%m-%d")
        lo, hi = ws, ws + timedelta(days=6)
        assert w["intensity"] in ("high", "normal", "low")
        assert len(w["posts"]) == w["posts_recommended"], (
            f"week {w['week_index']}: {len(w['posts'])} posts != "
            f"posts_recommended {w['posts_recommended']}")
        seen_dates = set()
        for p in w["posts"]:
            d = datetime.strptime(p["date"], "%Y-%m-%d")
            assert lo <= d <= hi, (
                f"week {w['week_index']} post date {p['date']} outside "
                f"window [{lo.date()}, {hi.date()}]")
            assert p["date"] not in seen_dates, "duplicate post date in a week"
            seen_dates.add(p["date"])
            assert p["day_of_week"] == DAY_FR[d.weekday()], "day_of_week mismatch"
            for fld in ("caption", "hook", "ad_angle",
                        "production_guide", "visual_recommendation"):
                assert isinstance(p[fld], str) and p[fld], f"empty {fld}"


# ═══════════════════════════════════════════════════════════════════════════════
#  PER-INDUSTRY PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def build_industry(industry: str, llm, no_llm: bool) -> Optional[Dict[str, Any]]:
    print(f"\n  [{industry.upper()}]")
    forecast = load_prophet(industry)
    facts    = load_facts(industry)
    if forecast is None or facts is None:
        return None

    # Campaign window = first Prophet week .. last (4th) Prophet week + 6 days.
    # Drives the date-aware seasonal filter (FIX 3).
    win_lo = datetime.strptime(forecast[0]["week"], "%Y-%m-%d")
    win_hi = datetime.strptime(forecast[-1]["week"], "%Y-%m-%d") + timedelta(days=6)

    pools = build_pools(industry, facts, win_lo, win_hi)
    g     = build_grounding(industry, facts, win_lo, win_hi)
    camp  = build_skeleton(industry, forecast, facts, pools)

    n_posts = sum(len(w["posts"]) for w in camp["weeks"])
    print(f"    Anchor : {camp['anchor_week']}  | weeks: "
          + " ".join(f"{w['week_start']}({w['intensity']}×{w['posts_recommended']})"
                     for w in camp["weeks"]))
    print(f"    Window : {win_lo.date()} → {win_hi.date()}  | themes kept: "
          + ", ".join(t["topic_name"] for t in pools["themes_pool"]))
    print(f"    Posts  : {n_posts}  | LLM calls planned: "
          f"{0 if no_llm else n_posts + 1}")

    stats = {"OK": 0, "REPAIRED": 0, "FALLBACK": 0}
    t0 = time.perf_counter()

    def _bump(status: str) -> None:
        if no_llm:
            return
        key = "FALLBACK" if status.startswith("FALLBACK") else status
        if key in stats:
            stats[key] += 1

    # campaign_summary
    if no_llm:
        sm, st = fallback_summary(industry, g), "NO_LLM"
    else:
        sm, st = generate_summary(llm, industry, g)
    camp["campaign_summary"].update(sm)
    camp["campaign_summary"]["status"] = st
    _bump(st)

    # posts
    for w in camp["weeks"]:
        for p in w["posts"]:
            if no_llm:
                fields, status = fallback_post(industry, p, g), "NO_LLM"
            else:
                fields, status = generate_post(llm, industry, p, g)
            p.update(fields)
            p["status"] = status
            p.pop("_k", None)                          # drop transient seed
            _bump(status)
            print(f"    w{w['week_index']} {p['date']} {p['day_of_week']:<9} "
                  f"{p['format']:<8} {p['theme'][:28]:<28} {status}")

    camp["generation"] = {
        "no_llm":          no_llm,
        "n_posts":         n_posts,
        "elapsed_seconds": round(time.perf_counter() - t0, 1),
        "status_counts":   stats,
    }

    validate_schema(camp)                                  # raises on any breach

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"campaign_{industry}.json"
    out.write_text(json.dumps(camp, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"    ✔ schema OK | {stats} | {camp['generation']['elapsed_seconds']}s "
          f"→ {out.relative_to(ROOT)}")
    return camp


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="Step 5 — Campaign Generator")
    ap.add_argument("--industry", choices=INDUSTRIES + ["all"], default="all")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip Ollama; deterministic fallback text only "
                         "(instant — verifies template + dates + schema)")
    args = ap.parse_args()
    industries = INDUSTRIES if args.industry == "all" else [args.industry]

    print("=" * 78)
    print("campaign_generator.py — Step 5 (hybrid template + llama3.1)")
    print(f"Industries : {industries}   no_llm={args.no_llm}")
    print("=" * 78)

    llm = None
    if not args.no_llm:
        print("\nLoading Ollama ...")
        from langchain_ollama import OllamaLLM
        llm = OllamaLLM(model=LLM_MODEL, temperature=TEMPERATURE,
                        num_ctx=NUM_CTX, num_predict=NUM_PREDICT,
                        timeout=TIMEOUT_S)
        print(f"  llm={LLM_MODEL} temp={TEMPERATURE} "
              f"num_predict={NUM_PREDICT}")

    done, failed = [], []
    for ind in industries:
        try:
            r = build_industry(ind, llm, args.no_llm)
            (done if r else failed).append(ind)
        except AssertionError as e:
            print(f"    ✗ SCHEMA VIOLATION ({ind}): {e}")
            failed.append(ind)

    print("\n" + "=" * 78)
    print(f"campaign_generator.py — complete | ok={done} | failed={failed}")
    print("=" * 78)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
