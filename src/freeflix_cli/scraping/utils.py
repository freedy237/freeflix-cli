from __future__ import annotations

from typing import List
import re
from .objects import Player, Episode


def parse_episodes_from_js(js_code: str) -> List[Episode]:
    """
    Parse a JavaScript code into a list of episodes.
    """
    matches = re.findall(r"var\s+eps(\d+)\s*=\s*\[(.*?)\];", js_code, re.DOTALL)

    lecteurs = {}
    for lecteur_num, content in matches:
        urls = re.findall(r"'(https?://.*?)'", content)
        urls += [u for u in re.findall(r'"(https?://.*?)"', content) if u not in urls]
        lecteurs[int(lecteur_num)] = urls

    lecteurs = dict(sorted(lecteurs.items()))

    if not lecteurs:
        return []
    max_episodes = max(len(lst) for lst in lecteurs.values())

    lecteur_names = [f"Lecteur {i+1}" for i in range(len(lecteurs))]

    episodes = []
    for i in range(max_episodes):
        players = []
        for name, urls in zip(lecteur_names, lecteurs.values()):
            url = urls[i] if i < len(urls) else None
            if url:
                players.append(Player(name, url))
        episodes.append(Episode(title=f"Épisode {i+1}", players=players))

    return episodes


def parse_html(markup):
    """BeautifulSoup with the FAST lxml parser when available, falling back to
    html5lib (lenient, always installed). lxml is ~10-30x faster on big pages,
    so sources feel snappier ; the fallback keeps parsing working everywhere
    (e.g. a Termux env without a compiled lxml)."""
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception:
        return BeautifulSoup(markup, "html5lib")
