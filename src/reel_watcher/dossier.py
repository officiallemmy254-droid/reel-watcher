"""Creator Intelligence Dossier & Playbook Synthesis Engine (`dossier.py`).

Aggregates individual studied reels into an executive competitive intelligence
dossier:
- Top Outlier Hook Swipe File & Formulas
- Funnel Blueprint: Lead magnets, ManyChat comment trigger keywords, and CTAs
- Editing Cadence & Pacing Benchmarks (duration, cut frequency)
- Reusable Gwelix Script Templates derived from viral outliers
Renders structured JSON and publication-grade Markdown reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from reel_watcher.config import format_status
from reel_watcher.db import Vault


def synthesize_creator_dossier(
    handle: str,
    vault: Vault,
    platform: str = "instagram",
) -> dict[str, Any]:
    """Aggregate all studied reels for a creator into a structured intelligence dossier.

    Parameters
    ----------
    handle : str
        Creator handle or username.
    vault : Vault
        Active SQLite Vault instance.
    platform : str
        Target platform (default: 'instagram').

    Returns
    -------
    dict[str, Any]
        Dossier dictionary with hooks, funnels, pacing, and playbook templates.
    """
    clean_handle = handle.strip().lstrip("@").lower()
    creator_info = vault.get_creator(clean_handle, platform=platform) or {}
    creator_id = creator_info.get("id")

    # Fetch studies linked to creator_id, or fallback to author string search
    studies: list[dict[str, Any]] = []
    if creator_id is not None:
        studies = vault.get_studies_by_creator(creator_id)

    if not studies:
        all_studies = vault.list_studies(limit=200, query=clean_handle)
        studies = [s for s in all_studies if clean_handle in str(s.get("author", "")).lower()]

    # Sort studies by outlier multiplier or views descending
    studies.sort(
        key=lambda s: (
            float(s.get("outlier_multiplier") or 0.0),
            int(s.get("views") or 0),
            float(s.get("score") or 0.0),
        ),
        reverse=True,
    )

    total_studies = len(studies)
    total_views = sum(int(s.get("views") or 0) for s in studies)
    avg_score = (
        round(sum(float(s.get("score") or 0.0) for s in studies) / total_studies, 2)
        if total_studies > 0
        else 0.0
    )

    # 1. Hook Analysis
    top_hooks: list[dict[str, Any]] = []
    framework_counts: dict[str, int] = {}

    for s in studies:
        hook_txt = str(s.get("hook_text") or "").strip()
        frm = str(s.get("framework") or "Direct Statement").strip()
        if frm:
            framework_counts[frm] = framework_counts.get(frm, 0) + 1

        if hook_txt:
            top_hooks.append({
                "shortcode": s.get("shortcode", ""),
                "title": s.get("title", ""),
                "hook_text": hook_txt,
                "framework": frm,
                "views": int(s.get("views") or 0),
                "outlier_multiplier": float(s.get("outlier_multiplier") or 1.0),
                "score": float(s.get("score") or 0.0),
            })

    # 2. Funnel & Offer Extraction
    comment_triggers: list[str] = []
    offers_found: list[str] = []
    cta_actions: dict[str, int] = {}

    for s in studies:
        giveaway = s.get("giveaway") or {}
        if isinstance(giveaway, dict) and giveaway.get("has_giveaway"):
            action = giveaway.get("action", "unknown")
            cta_actions[action] = cta_actions.get(action, 0) + 1

            for w in giveaway.get("comment_words", []):
                clean_w = str(w).upper().strip()
                if clean_w and clean_w not in comment_triggers:
                    comment_triggers.append(clean_w)

            offer = str(giveaway.get("offer") or "").strip()
            if offer and offer not in offers_found:
                offers_found.append(offer)

    # 3. Pacing & Editing Benchmarks
    durations = [float(s.get("duration") or 0.0) for s in studies if float(s.get("duration") or 0.0) > 0]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    cut_counts = [int(s.get("cuts_count") or 0) for s in studies if int(s.get("cuts_count") or 0) > 0]
    avg_cuts = round(sum(cut_counts) / len(cut_counts), 1) if cut_counts else 0.0
    cuts_per_minute = round((avg_cuts / (avg_duration / 60)), 1) if avg_duration > 0 else 0.0

    # 4. Gwelix Script Framework Derivations
    script_templates: list[dict[str, str]] = []
    for h in top_hooks[:3]:
        raw_hook = h["hook_text"]
        frm = h["framework"]
        templated = re.sub(r"\b\d+\b", "[NUMBER]", raw_hook)
        script_templates.append({
            "framework": frm,
            "original_hook": raw_hook,
            "universal_formula": templated,
        })

    return {
        "handle": clean_handle,
        "platform": platform,
        "creator_profile": creator_info,
        "total_studies": total_studies,
        "total_views": total_views,
        "average_score": avg_score,
        "top_hooks": top_hooks,
        "framework_distribution": framework_counts,
        "funnel": {
            "comment_triggers": comment_triggers,
            "offers": offers_found,
            "cta_distribution": cta_actions,
        },
        "pacing": {
            "avg_duration": avg_duration,
            "avg_cuts": avg_cuts,
            "cuts_per_minute": cuts_per_minute,
        },
        "script_templates": script_templates,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_dossier_markdown(dossier: dict[str, Any]) -> str:
    """Render structured creator dossier into clean, executive Markdown report."""
    handle = dossier.get("handle", "unknown")
    platform = dossier.get("platform", "instagram")
    total_studies = dossier.get("total_studies", 0)
    avg_score = dossier.get("average_score", 0.0)
    pacing = dossier.get("pacing", {})
    funnel = dossier.get("funnel", {})
    hooks = dossier.get("top_hooks", [])
    templates = dossier.get("script_templates", [])

    lines = [
        f"# Creator Intelligence Dossier: @{handle}",
        f"*Platform: {platform.title()} | Studied Outliers: {total_studies} | Average Score: {avg_score}/10*",
        "",
        "---",
        "",
        "## 1. Executive Summary & Baselines",
        f"- **Total Studied Reels:** {total_studies}",
        f"- **Average Video Duration:** {pacing.get('avg_duration', 0)} seconds",
        f"- **Scene Cut Cadence:** ~{pacing.get('cuts_per_minute', 0)} cuts/min ({pacing.get('avg_cuts', 0)} scene transitions per reel)",
        "",
        "## 2. Top Outlier Hooks Swipe File",
    ]

    if not hooks:
        lines.append("*No completed reel studies recorded for this creator yet.*")
    else:
        for idx, h in enumerate(hooks[:5], 1):
            mult = h.get("outlier_multiplier", 1.0)
            views = f"{h.get('views', 0):,}" if h.get("views") else "N/A"
            lines.extend([
                f"### {idx}. {h.get('framework', 'Hook')} (Outlier Score: {mult}x)",
                f"> \"{h.get('hook_text', '')}\"",
                f"- **Views:** {views} | **Score:** {h.get('score', 0)}/10",
                f"- **Title:** {h.get('title', 'Reel')}",
                "",
            ])

    lines.extend([
        "## 3. Funnel & Lead Magnet Blueprint",
        f"- **ManyChat Comment Keywords:** {', '.join(funnel.get('comment_triggers', [])) or 'None detected'}",
        f"- **Detected Lead Magnets & Offers:** {', '.join(funnel.get('offers', [])) or 'None detected'}",
        "",
        "## 4. Reusable Gwelix Script Templates",
    ])

    if not templates:
        lines.append("*No script templates generated yet.*")
    else:
        for idx, t in enumerate(templates, 1):
            lines.extend([
                f"#### Template {idx}: {t.get('framework', 'Formula')}",
                f"- **Pattern:** `{t.get('universal_formula', '')}`",
                f"- **Reference Original:** *\"{t.get('original_hook', '')}\"*",
                "",
            ])

    return "\n".join(lines)


def export_dossier(
    handle: str,
    vault: Vault,
    out_dir: Path | str | None = None,
    platform: str = "instagram",
) -> Path:
    """Generate and write dossier markdown and JSON report to disk."""
    clean_handle = handle.strip().lstrip("@").lower()
    dest_dir = Path(out_dir) if out_dir else vault.out_root / "creators" / clean_handle
    dest_dir.mkdir(parents=True, exist_ok=True)

    dossier = synthesize_creator_dossier(handle=clean_handle, vault=vault, platform=platform)
    md_content = render_dossier_markdown(dossier)

    md_file = dest_dir / "dossier.md"
    json_file = dest_dir / "dossier.json"

    md_file.write_text(md_content, encoding="utf-8")
    json_file.write_text(json.dumps(dossier, indent=2, ensure_ascii=False), encoding="utf-8")

    return md_file
