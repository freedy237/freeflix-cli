"""
Bilingual completeness guard (FR/EN) : FreeFlix must leave no user-facing
English untranslated.

1. Every t()/"_t()" literal key must exist in _FR (else FR shows English).
2. Every literal/f-string chunk printed to the console via the UI helpers
   must either be wrapped in t() or belong to the frozen TECHNICAL set
   (Rich markup, commands, URLs, brand names, units, bilingual-by-design
   wizard lines). Any NEW prose added without t() fails here.
"""

import ast
import glob
import re

from freeflix_cli.i18n import _FR

UI_FUNCS = {
    "print_success", "print_error", "print_warning", "print_info",
    "spinner", "select_from_list", "select_with_preview", "select_multiple",
    "get_user_input", "confirm_or_timeout", "toast", "print_header", "print",
}

# Frozen : reviewed 2026-10-11, all non-linguistic (markup fragments around
# wrapped prose, shell commands, URLs/paths, binary & brand names, units,
# bilingual language-picker lines shown before the UI language is known).
TECHNICAL = {
    "! chafa",
    "' → High-performance Nvidia",
    "'CaskaydiaCove Nerd Font'.",
    "(https://hpjansson.org/chafa/).",
    "2. scripts/install.ps1",
    "AniList",
    "Anime language set to / Langue des animes :",
    "B <",
    "B) —",
    "Do you want anime in English (VO/sub) or in French (VF/VOSTFR)?",
    "FreeFlix CLI —",
    "MB",
    "Voulez-vous les animes en anglais (VO/sous-titres) ou en français (VF/VOSTFR) ?",
    "aria2c",
    "brew install podman && podman machine init && podman machine start",
    "chafa",
    "dev",
    "export PATH=\"$HOME/.local/bin:$PATH\"",
    "freeflix",
    "freeflix --doctor",
    "freeflix --doctor --sources",
    "freeflix --doctor --upload",
    "freeflix --help",
    "freeflix --setup",
    "freeflix --verbose",
    "freeflix --version",
    "http://",
    "https://f-droid.org/packages/is.xyz.mpv/",
    "m",
    "powershell -ExecutionPolicy Bypass -File scripts\\install.ps1",
    "s",
    "sudo dnf install aria2",
    "sudo dnf install aria2 yt-dlp",
    "sudo dnf install yt-dlp",
    "termux-setup-storage",
    "winget install Docker.DockerDesktop",
    "→ C:\\Program Files\\mpv\\mpv.exe (or mpv.net)",
    "✓ chafa",
    "🎴 Anime language  /  Langue des animes",
    "Choice / Choix:",
    "[bold",
    "[/bold",
}


def _strip_markup(s: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", s)


def _emit_chunk(out, loc, s):
    st = s.strip()
    if st and re.search(r"[A-Za-zÀ-ÿ]", st):
        out.append((st, loc))


def _grab_operand(out, loc, n):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        _emit_chunk(out, loc, n.value)
    elif isinstance(n, ast.JoinedStr):
        for v in n.values:
            if isinstance(v, ast.Constant):
                _emit_chunk(out, loc, v.value)
    elif isinstance(n, ast.BinOp):
        _grab_operand(out, loc, n.left)
        _grab_operand(out, loc, n.right)
    # t()/"_t()" operand : already translated, skip


def _ui_chunks():
    """(text, location) for every console-printed literal chunk."""
    out = []
    for fp in glob.glob("src/freeflix_cli/**/*.py", recursive=True):
        if fp.endswith("i18n.py"):
            continue
        tree = ast.parse(open(fp).read())
        for node in ast.walk(tree):
            fn = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in UI_FUNCS
                and node.args
            ):
                fn = node.func.id
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "print"
                and node.args
            ):
                fn = "console.print"
            if not fn:
                continue
            loc = f"{fp.split('/')[-1]}:{node.lineno}"
            arg = node.args[0]

            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id in ("t", "_t")
            ):
                continue  # fully wrapped call
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                _emit_chunk(out, loc, arg.value)
            elif isinstance(arg, ast.JoinedStr):
                for v in arg.values:
                    if isinstance(v, ast.Constant):
                        _emit_chunk(out, loc, v.value)
            elif isinstance(arg, ast.BinOp):
                _grab_operand(out, loc, arg)
    return out


def _used_keys():
    used = set()
    for fp in glob.glob("src/freeflix_cli/**/*.py", recursive=True):
        if fp.endswith("i18n.py"):
            continue
        for node in ast.walk(ast.parse(open(fp).read())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("t", "_t")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                used.add(node.args[0].value)
    return used


def test_every_t_key_has_french():
    missing = sorted(k for k in _used_keys() if k not in _FR)
    assert not missing, f"t() keys without FR entry: {missing}"


def test_no_unwrapped_user_prose():
    violations = []
    for text, loc in _ui_chunks():
        if text in _FR:
            violations.append(f"{loc}: known key used WITHOUT t(): {text!r:.80}")
        elif text in TECHNICAL:
            continue
        elif not re.search(r"[A-Za-zÀ-ÿ]", _strip_markup(text)):
            continue  # pure Rich markup / symbols
        else:
            violations.append(f"{loc}: unwrapped prose: {text!r:.80}")
    assert not violations, "\n".join(violations)
