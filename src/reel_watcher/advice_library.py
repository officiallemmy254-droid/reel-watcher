"""Static Advice Library & Playbook Generator (`advice_library.py`).

Generates self-contained, interactive HTML advice libraries deconstructed from
saved studies in the Reel-Watcher Vault. Zero external network dependencies,
embedded CSS/JS, with localStorage persistence for checklists and creative notes.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from reel_watcher.config import format_status


def render_advice_html(
    studies: list[dict[str, Any]],
    out_path: Path | str,
    title: str = "Reel-Watcher Advice Library",
) -> Path:
    """Render a self-contained, interactive HTML advice library.

    Parameters
    ----------
    studies : list[dict[str, Any]]
        List of study dictionaries produced by study deconstruction pipeline.
    out_path : Path | str
        Target filesystem path for the output HTML document.
    title : str, optional
        Document title and header headline (default: 'Reel-Watcher Advice Library').

    Returns
    -------
    Path
        Resolved Path object pointing to the written HTML file.
    """
    dest = Path(out_path)
    if dest.parent:
        dest.parent.mkdir(parents=True, exist_ok=True)

    escaped_title = html.escape(title)

    # Compute aggregate metrics
    total_count = len(studies)
    valid_scores = [
        float(s.get("score", 0.0))
        for s in studies
        if s.get("score") is not None and float(s.get("score", 0.0)) > 0
    ]
    avg_score = (sum(valid_scores) / len(valid_scores)) if valid_scores else 0.0

    giveaway_count = sum(
        1
        for s in studies
        if s.get("giveaway", {}).get("has_giveaway")
        or s.get("visual_analysis", {}).get("cta", {}).get("action")
    )

    frameworks_set = {
        s.get("framework")
        for s in studies
        if s.get("framework") and str(s.get("framework")).strip()
    }

    # Generate study cards HTML
    cards_html_parts: list[str] = []

    if not studies:
        cards_html_parts.append(
            """
            <div class="empty-state">
                <div class="empty-icon">[!]</div>
                <h2>No studies found</h2>
                <p>Run <code>reel-watcher study &lt;media&gt;</code> to deconstruct reels and populate this library.</p>
            </div>
            """
        )
    else:
        for idx, s in enumerate(studies):
            code = html.escape(str(s.get("code") or s.get("shortcode") or f"study_{idx}"))
            item_title = html.escape(str(s.get("title") or f"Reel {code}"))
            author = html.escape(str(s.get("author") or "Unknown Creator"))
            collection = html.escape(str(s.get("collection") or "general"))
            url = html.escape(str(s.get("url") or ""))
            hook_text = html.escape(str(s.get("hook_text") or ""))
            summary = html.escape(str(s.get("summary") or ""))
            framework = html.escape(str(s.get("framework") or "Direct Breakdown"))

            raw_score = s.get("score", 0.0)
            try:
                score = float(raw_score)
            except (ValueError, TypeError):
                score = 0.0

            duration = float(s.get("duration", 0.0))
            cuts_count = int(s.get("cuts_count", len(s.get("cuts") or [])))

            # Giveaway / CTA info
            gw = s.get("giveaway") or {}
            has_giveaway = bool(gw.get("has_giveaway"))
            comment_words = [html.escape(str(w)) for w in gw.get("comment_words") or []]
            gw_action = html.escape(str(gw.get("action") or ""))
            gw_offer = html.escape(str(gw.get("offer") or ""))

            # Visual analysis
            vlm = s.get("visual_analysis") or {}
            vlm_hook = vlm.get("hook") or {}
            hook_style = ""
            hook_rating = 0.0
            if isinstance(vlm_hook, dict):
                hook_style = html.escape(str(vlm_hook.get("visual_style") or ""))
                try:
                    hook_rating = float(vlm_hook.get("rating") or vlm_hook.get("strength") or 0.0)
                except (ValueError, TypeError):
                    hook_rating = 0.0

            strengths = [html.escape(str(item)) for item in vlm.get("strengths") or []]
            weaknesses = [html.escape(str(item)) for item in vlm.get("weaknesses") or []]

            # Contact sheet
            sheet_path = html.escape(str(s.get("contact_sheet") or ""))

            # Audio analysis
            audio = s.get("audio_analysis") or {}
            has_music = bool(audio.get("has_music_bed"))
            speech_ratio = float(audio.get("speech_ratio") or 0.0)

            # Searchable payload
            search_data = (
                f"{item_title} {author} {collection} {hook_text} {summary} "
                f"{framework} {' '.join(comment_words)} {gw_action} {gw_offer}"
            ).lower()

            card = f"""
            <article class="study-card" data-code="{code}" data-score="{score:.1f}" data-framework="{framework}" data-giveaway="{'true' if has_giveaway else 'false'}" data-search="{html.escape(search_data)}">
                <header class="card-header">
                    <div class="header-main">
                        <span class="badge badge-collection">{collection}</span>
                        <h3 class="card-title">{item_title}</h3>
                        <div class="card-meta">
                            <span class="author-tag">by <strong>@{author}</strong></span>
                            <span class="code-tag">ID: <code>{code}</code></span>
                        </div>
                    </div>
                    <div class="header-score">
                        <div class="score-box" title="Deconstruction Score">
                            <span class="score-value">{score:.1f}</span>
                            <span class="score-max">/10</span>
                        </div>
                    </div>
                </header>

                <div class="card-body">
                    <!-- Hook Deconstruction -->
                    <div class="section-box hook-box">
                        <div class="section-label">Hook Pattern</div>
                        <blockquote class="hook-quote">"{hook_text if hook_text else 'No explicit text hook detected'}"</blockquote>
                        <div class="hook-details">
                            {f'<span class="detail-pill"><strong>Style:</strong> {hook_style}</span>' if hook_style else ''}
                            {f'<span class="detail-pill highlight"><strong>Hook Rating:</strong> {hook_rating:.1f}/10</span>' if hook_rating > 0 else ''}
                        </div>
                    </div>

                    <!-- Framework & Metrics -->
                    <div class="section-box framework-box">
                        <div class="section-label">Structure &amp; Pacing</div>
                        <div class="framework-chips">
                            <span class="chip chip-framework">{framework}</span>
                            <span class="chip chip-metric">{duration:.1f}s Duration</span>
                            <span class="chip chip-metric">{cuts_count} Scene Cuts</span>
                            <span class="chip chip-metric">Music Bed: {'Yes' if has_music else 'No'}</span>
                            {f'<span class="chip chip-metric">Speech Ratio: {int(speech_ratio*100)}%</span>' if speech_ratio > 0 else ''}
                        </div>
                    </div>

                    <!-- Giveaway & CTA Funnel -->
                    {f'''
                    <div class="section-box cta-box">
                        <div class="section-label">Conversion Funnel &amp; Giveaway</div>
                        <div class="cta-content">
                            <span class="badge badge-funnel">{gw_action.upper() if gw_action else 'CTA'}</span>
                            {f'<span class="keyword-pill">Keyword: <strong>"{comment_words[0]}"</strong></span>' if comment_words else ''}
                            {f'<p class="offer-desc"><strong>Offer:</strong> {gw_offer}</p>' if gw_offer else ''}
                        </div>
                    </div>
                    ''' if (has_giveaway or comment_words or gw_offer) else ''}

                    <!-- Strengths and Weaknesses -->
                    <div class="section-box feedback-box">
                        {f'''
                        <div class="feedback-col">
                            <div class="feedback-label positive">[+] Strengths</div>
                            <ul class="feedback-list">
                                {''.join(f'<li>{st}</li>' for st in strengths)}
                            </ul>
                        </div>
                        ''' if strengths else ''}
                        {f'''
                        <div class="feedback-col">
                            <div class="feedback-label alert">[!] Growth Areas</div>
                            <ul class="feedback-list">
                                {''.join(f'<li>{wk}</li>' for wk in weaknesses)}
                            </ul>
                        </div>
                        ''' if weaknesses else ''}
                    </div>

                    <!-- Actionable Implementation Checklist -->
                    <div class="section-box checklist-box">
                        <div class="section-label">Tactical Production Checklist</div>
                        <div class="checklist-items">
                            <label class="check-item" for="rw_chk_{code}_hook">
                                <input type="checkbox" id="rw_chk_{code}_hook" data-id="rw_chk_{code}_hook" class="persist-check">
                                <span>Hook: Replicate "{hook_text[:40]}..." angle</span>
                            </label>
                            <label class="check-item" for="rw_chk_{code}_pacing">
                                <input type="checkbox" id="rw_chk_{code}_pacing" data-id="rw_chk_{code}_pacing" class="persist-check">
                                <span>Pacing: Structure with {framework} across {cuts_count} shot transitions</span>
                            </label>
                            <label class="check-item" for="rw_chk_{code}_funnel">
                                <input type="checkbox" id="rw_chk_{code}_funnel" data-id="rw_chk_{code}_funnel" class="persist-check">
                                <span>Funnel: Apply {gw_action if gw_action else 'direct CTA'} trigger automation</span>
                            </label>
                            <label class="check-item" for="rw_chk_{code}_audio">
                                <input type="checkbox" id="rw_chk_{code}_audio" data-id="rw_chk_{code}_audio" class="persist-check">
                                <span>Audio: Maintain continuous background bed at -18dB</span>
                            </label>
                        </div>
                    </div>

                    <!-- Persistent Production Notes -->
                    <div class="section-box notes-box">
                        <div class="notes-header">
                            <span class="section-label">Creator Playbook Notes</span>
                            <span class="save-status" id="rw_status_{code}">Saved</span>
                        </div>
                        <textarea id="rw_note_{code}" data-id="rw_note_{code}" class="persist-note" placeholder="Write creator adaptation ideas, script hooks, or production notes here (auto-saved)..."></textarea>
                    </div>

                    {f'''
                    <footer class="card-footer">
                        {f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="link-btn">Watch Original Reel &rarr;</a>' if url else ''}
                        {f'<span class="sheet-ref">Contact Sheet: <code>{sheet_path}</code></span>' if sheet_path else ''}
                    </footer>
                    ''' if (url or sheet_path) else ''}
                </div>
            </article>
            """
            cards_html_parts.append(card)

    rendered_cards = "\n".join(cards_html_parts)

    html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title}</title>
    <style>
        :root {{
            --bg-canvas: #090d16;
            --bg-surface: #111726;
            --bg-surface-elevated: #1a233a;
            --bg-surface-soft: #232d4b;
            --border-subtle: #242f4c;
            --border-hover: #3b4b73;
            --text-main: #e2e8f0;
            --text-heading: #ffffff;
            --text-muted: #8b9bb4;
            --accent-cyan: #38bdf8;
            --accent-green: #34d399;
            --accent-amber: #fbbf24;
            --accent-purple: #c084fc;
            --accent-rose: #fb7185;
            --radius-sm: 6px;
            --radius-md: 10px;
            --radius-lg: 14px;
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --font-mono: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-canvas);
            color: var(--text-main);
            font-family: var(--font-sans);
            line-height: 1.5;
            padding: 2rem 1.5rem 4rem;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        /* Header & Brand */
        header.page-header {{
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-subtle);
            padding-bottom: 1.5rem;
        }}

        .brand-badge {{
            display: inline-block;
            font-size: 0.75rem;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.1em;
            color: var(--accent-cyan);
            background: rgba(56, 189, 248, 0.12);
            padding: 0.25rem 0.6rem;
            border-radius: var(--radius-sm);
            margin-bottom: 0.75rem;
            border: 1px solid rgba(56, 189, 248, 0.2);
        }}

        h1.page-title {{
            font-size: 2.25rem;
            font-weight: 800;
            color: var(--text-heading);
            letter-spacing: -0.02em;
            margin-bottom: 0.5rem;
        }}

        p.page-subtitle {{
            color: var(--text-muted);
            font-size: 1rem;
            max-width: 720px;
        }}

        /* Metrics Bar */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        .metric-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}

        .metric-label {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            font-weight: 600;
        }}

        .metric-val {{
            font-size: 1.85rem;
            font-weight: 800;
            color: var(--text-heading);
        }}

        .metric-note {{
            font-size: 0.75rem;
            color: var(--accent-cyan);
        }}

        /* Controls / Filter Bar */
        .controls-bar {{
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            padding: 1rem;
            margin-bottom: 2rem;
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            align-items: center;
            justify-content: space-between;
        }}

        .search-box {{
            flex: 1 1 300px;
        }}

        .search-input {{
            width: 100%;
            background: var(--bg-canvas);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-sm);
            color: var(--text-heading);
            padding: 0.6rem 0.9rem;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.15s ease;
        }}

        .search-input:focus {{
            border-color: var(--accent-cyan);
        }}

        .filter-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}

        .btn {{
            background: var(--bg-surface-elevated);
            color: var(--text-main);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-sm);
            padding: 0.45rem 0.85rem;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .btn:hover {{
            background: var(--bg-surface-soft);
            border-color: var(--border-hover);
            color: var(--text-heading);
        }}

        .btn.active {{
            background: rgba(56, 189, 248, 0.18);
            border-color: var(--accent-cyan);
            color: var(--accent-cyan);
        }}

        .btn-reset {{
            color: var(--accent-rose);
            border-color: rgba(251, 113, 133, 0.25);
        }}

        .btn-reset:hover {{
            background: rgba(251, 113, 133, 0.15);
        }}

        /* Study Cards List */
        .cards-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 1.5rem;
        }}

        .study-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-lg);
            overflow: hidden;
            transition: border-color 0.2s ease, transform 0.2s ease;
        }}

        .study-card:hover {{
            border-color: var(--border-hover);
        }}

        .card-header {{
            background: var(--bg-surface-elevated);
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border-subtle);
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }}

        .header-main {{
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }}

        .card-title {{
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-heading);
            letter-spacing: -0.01em;
        }}

        .card-meta {{
            font-size: 0.82rem;
            color: var(--text-muted);
            display: flex;
            gap: 0.75rem;
            align-items: center;
        }}

        .code-tag code {{
            background: var(--bg-canvas);
            padding: 0.15rem 0.35rem;
            border-radius: var(--radius-sm);
            font-family: var(--font-mono);
            font-size: 0.75rem;
            color: var(--accent-cyan);
        }}

        .score-box {{
            background: rgba(52, 211, 153, 0.12);
            border: 1px solid rgba(52, 211, 153, 0.3);
            border-radius: var(--radius-md);
            padding: 0.4rem 0.75rem;
            text-align: center;
            min-width: 68px;
        }}

        .score-value {{
            font-size: 1.25rem;
            font-weight: 800;
            color: var(--accent-green);
        }}

        .score-max {{
            font-size: 0.7rem;
            color: var(--text-muted);
            font-weight: 600;
        }}

        .card-body {{
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }}

        .section-box {{
            background: var(--bg-surface-elevated);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            padding: 1rem 1.25rem;
        }}

        .section-label {{
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}

        /* Hook Box */
        .hook-quote {{
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--accent-cyan);
            border-left: 3px solid var(--accent-cyan);
            padding-left: 0.85rem;
            margin-bottom: 0.5rem;
            font-style: italic;
        }}

        .hook-details {{
            display: flex;
            gap: 0.6rem;
            flex-wrap: wrap;
        }}

        .detail-pill {{
            font-size: 0.78rem;
            background: var(--bg-canvas);
            padding: 0.2rem 0.5rem;
            border-radius: var(--radius-sm);
            color: var(--text-main);
        }}

        .detail-pill.highlight {{
            color: var(--accent-amber);
            border: 1px solid rgba(251, 191, 36, 0.3);
        }}

        /* Framework chips */
        .framework-chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}

        .chip {{
            font-size: 0.78rem;
            font-weight: 600;
            padding: 0.25rem 0.6rem;
            border-radius: var(--radius-sm);
            background: var(--bg-canvas);
            color: var(--text-main);
            border: 1px solid var(--border-subtle);
        }}

        .chip-framework {{
            background: rgba(192, 132, 252, 0.15);
            border-color: rgba(192, 132, 252, 0.35);
            color: var(--accent-purple);
        }}

        /* CTA & Funnel */
        .cta-content {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }}

        .badge {{
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            padding: 0.2rem 0.5rem;
            border-radius: var(--radius-sm);
        }}

        .badge-collection {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-cyan);
            align-self: flex-start;
        }}

        .badge-funnel {{
            background: rgba(52, 211, 153, 0.18);
            color: var(--accent-green);
        }}

        .keyword-pill {{
            background: var(--bg-canvas);
            border: 1px solid var(--border-subtle);
            padding: 0.2rem 0.5rem;
            border-radius: var(--radius-sm);
            font-size: 0.8rem;
            color: var(--accent-amber);
        }}

        .offer-desc {{
            font-size: 0.85rem;
            color: var(--text-main);
        }}

        /* Feedback / Strengths */
        .feedback-box {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem;
        }}

        .feedback-label {{
            font-size: 0.78rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }}

        .feedback-label.positive {{
            color: var(--accent-green);
        }}

        .feedback-label.alert {{
            color: var(--accent-rose);
        }}

        .feedback-list {{
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}

        .feedback-list li {{
            font-size: 0.82rem;
            color: var(--text-main);
            padding-left: 0.85rem;
            position: relative;
        }}

        .feedback-list li::before {{
            content: "•";
            position: absolute;
            left: 0;
            color: var(--text-muted);
        }}

        /* Checklist */
        .checklist-items {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}

        .check-item {{
            display: flex;
            align-items: center;
            gap: 0.65rem;
            font-size: 0.85rem;
            cursor: pointer;
            user-select: none;
            padding: 0.3rem 0.4rem;
            border-radius: var(--radius-sm);
            transition: background-color 0.15s ease;
        }}

        .check-item:hover {{
            background: var(--bg-canvas);
        }}

        .check-item input[type="checkbox"] {{
            accent-color: var(--accent-cyan);
            width: 16px;
            height: 16px;
            cursor: pointer;
        }}

        .check-item.completed span {{
            text-decoration: line-through;
            color: var(--text-muted);
        }}

        /* Notes */
        .notes-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.4rem;
        }}

        .save-status {{
            font-size: 0.7rem;
            color: var(--accent-green);
            opacity: 0;
            transition: opacity 0.3s ease;
        }}

        .save-status.visible {{
            opacity: 1;
        }}

        .persist-note {{
            width: 100%;
            min-height: 72px;
            background: var(--bg-canvas);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-sm);
            color: var(--text-heading);
            padding: 0.65rem;
            font-size: 0.85rem;
            font-family: var(--font-sans);
            resize: vertical;
            outline: none;
            transition: border-color 0.15s ease;
        }}

        .persist-note:focus {{
            border-color: var(--accent-cyan);
        }}

        /* Card footer */
        .card-footer {{
            border-top: 1px solid var(--border-subtle);
            padding-top: 0.75rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
            font-size: 0.8rem;
        }}

        .link-btn {{
            color: var(--accent-cyan);
            text-decoration: none;
            font-weight: 600;
        }}

        .link-btn:hover {{
            text-decoration: underline;
        }}

        .sheet-ref code {{
            color: var(--text-muted);
            font-family: var(--font-mono);
            font-size: 0.72rem;
        }}

        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 4rem 1rem;
            background: var(--bg-surface);
            border: 1px dashed var(--border-subtle);
            border-radius: var(--radius-lg);
        }}

        .empty-icon {{
            font-size: 2rem;
            color: var(--accent-amber);
            margin-bottom: 0.5rem;
            font-family: var(--font-mono);
        }}

        .empty-state h2 {{
            color: var(--text-heading);
            margin-bottom: 0.5rem;
        }}

        .empty-state p {{
            color: var(--text-muted);
            font-size: 0.95rem;
        }}

        .empty-state code {{
            background: var(--bg-canvas);
            padding: 0.2rem 0.4rem;
            border-radius: var(--radius-sm);
            color: var(--accent-cyan);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="page-header">
            <span class="brand-badge">[+] Reel-Watcher Creative Intelligence</span>
            <h1 class="page-title">{escaped_title}</h1>
            <p class="page-subtitle">Tactical hook deconstructions, narrative frameworks, pacing signals, and comment-to-DM conversion funnels harvested from top-performing short-form video assets.</p>
        </header>

        <!-- Aggregate Metrics -->
        <section class="metrics-grid">
            <div class="metric-card">
                <span class="metric-label">Analyzed Reels</span>
                <span class="metric-val">{total_count}</span>
                <span class="metric-note">Stored in SQLite Vault</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">Average Score</span>
                <span class="metric-val">{avg_score:.1f}</span>
                <span class="metric-note">Out of 10.0 scale</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">Giveaway Funnels</span>
                <span class="metric-val">{giveaway_count}</span>
                <span class="metric-note">Automated comment/DM CTAs</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">Unique Frameworks</span>
                <span class="metric-val">{len(frameworks_set)}</span>
                <span class="metric-note">Scripting structures</span>
            </div>
        </section>

        <!-- Interactive Controls -->
        <section class="controls-bar">
            <div class="search-box">
                <input type="text" id="search-input" class="search-input" placeholder="Search by hook, framework, author, or trigger keyword..." autocomplete="off">
            </div>
            <div class="filter-buttons">
                <button type="button" class="btn active" data-filter="all">All ({total_count})</button>
                <button type="button" class="btn" data-filter="high_score">Score &ge; 8.5</button>
                <button type="button" class="btn" data-filter="giveaways">Giveaways Only</button>
                <button type="button" class="btn btn-reset" id="reset-notes-btn">Clear Local Notes</button>
            </div>
        </section>

        <!-- Cards List -->
        <main class="cards-grid" id="cards-container">
            {rendered_cards}
        </main>
    </div>

    <!-- Self-Contained Local Persistence & Filtering Script -->
    <script>
        (function() {{
            // 1. Checkbox persistence via localStorage
            const checkboxes = document.querySelectorAll('.persist-check');
            checkboxes.forEach(chk => {{
                const key = chk.getAttribute('data-id');
                if (key) {{
                    const saved = localStorage.getItem(key);
                    if (saved === 'true') {{
                        chk.checked = true;
                        if (chk.parentElement) {{
                            chk.parentElement.classList.add('completed');
                        }}
                    }}
                }}

                chk.addEventListener('change', () => {{
                    const k = chk.getAttribute('data-id');
                    if (k) {{
                        localStorage.setItem(k, chk.checked ? 'true' : 'false');
                    }}
                    if (chk.parentElement) {{
                        if (chk.checked) {{
                            chk.parentElement.classList.add('completed');
                        }} else {{
                            chk.parentElement.classList.remove('completed');
                        }}
                    }}
                }});
            }});

            // 2. Note persistence via localStorage with debounced save status
            const notes = document.querySelectorAll('.persist-note');
            notes.forEach(note => {{
                const key = note.getAttribute('data-id');
                if (key) {{
                    const saved = localStorage.getItem(key);
                    if (saved !== null) {{
                        note.value = saved;
                    }}
                }}

                const code = key ? key.replace('rw_note_', '') : '';
                const statusEl = document.getElementById('rw_status_' + code);

                note.addEventListener('input', () => {{
                    if (key) {{
                        localStorage.setItem(key, note.value);
                    }}
                    if (statusEl) {{
                        statusEl.classList.add('visible');
                        clearTimeout(note._statusTimer);
                        note._statusTimer = setTimeout(() => {{
                            statusEl.classList.remove('visible');
                        }}, 1500);
                    }}
                }});
            }});

            // 3. Clear Local Notes button
            const resetBtn = document.getElementById('reset-notes-btn');
            if (resetBtn) {{
                resetBtn.addEventListener('click', () => {{
                    if (window.confirm('Clear all local checkboxes and notes from browser storage?')) {{
                        checkboxes.forEach(c => {{
                            c.checked = false;
                            if (c.parentElement) c.parentElement.classList.remove('completed');
                            const k = c.getAttribute('data-id');
                            if (k) localStorage.removeItem(k);
                        }});
                        notes.forEach(n => {{
                            n.value = '';
                            const k = n.getAttribute('data-id');
                            if (k) localStorage.removeItem(k);
                        }});
                    }}
                }});
            }}

            // 4. Live Search and Filter
            const searchInput = document.getElementById('search-input');
            const filterBtns = document.querySelectorAll('.filter-buttons .btn[data-filter]');
            const cards = document.querySelectorAll('.study-card');
            let currentFilter = 'all';

            function applyFilters() {{
                const query = searchInput ? searchInput.value.toLowerCase().trim() : '';

                cards.forEach(card => {{
                    const score = parseFloat(card.getAttribute('data-score') || '0');
                    const isGiveaway = card.getAttribute('data-giveaway') === 'true';
                    const searchText = (card.getAttribute('data-search') || '').toLowerCase();

                    let matchesFilter = true;
                    if (currentFilter === 'high_score') {{
                        matchesFilter = score >= 8.5;
                    }} else if (currentFilter === 'giveaways') {{
                        matchesFilter = isGiveaway;
                    }}

                    let matchesQuery = true;
                    if (query) {{
                        matchesQuery = searchText.includes(query);
                    }}

                    if (matchesFilter && matchesQuery) {{
                        card.style.display = '';
                    }} else {{
                        card.style.display = 'none';
                    }}
                }});
            }}

            if (searchInput) {{
                searchInput.addEventListener('input', applyFilters);
            }}

            filterBtns.forEach(btn => {{
                btn.addEventListener('click', () => {{
                    filterBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    currentFilter = btn.getAttribute('data-filter') || 'all';
                    applyFilters();
                }});
            }});
        }})();
    </script>
</body>
</html>
"""

    dest.write_text(html_document, encoding="utf-8")
    print(format_status("success", f"Advice Library HTML rendered to {dest} ({len(studies)} studies)."))
    return dest
