import os
from ..config_loader import load_remote_jsonc, load_local_jsonc
from ..defaults import DEFAULT_SOURCE_PORTAL

# Remote config now points at OUR fork's repo (not PaulExplorer's) so we
# control the authoritative source URLs. When a site moves, we push a new
# data/source_portal.jsonc and every user picks it up on next launch.
REMOTE_CONFIG_URL = (
    "https://raw.githubusercontent.com/freedy237/freeflix-cli/main/"
    "data/source_portal.jsonc"
)

# The bundled override file can live in a few places depending on how the
# package was installed (editable checkout, hatchling shared-data, etc.).
# Try each candidate ; the first that exists wins.
_HERE = os.path.dirname(__file__)
_LOCAL_CANDIDATES = [
    # editable / source checkout : .../src/freeflix_cli/scraping/ -> ../../../data
    os.path.join(_HERE, "..", "..", "..", "data", "source_portal.jsonc"),
    # installed wheel : .../site-packages/freeflix_cli/ -> ../../../data
    os.path.join(_HERE, "..", "..", "data", "source_portal.jsonc"),
    # hatchling shared-data : <venv>/share/freeflix-cli/data/
    os.path.join(_HERE, "..", "..", "..", "..", "..", "share", "freeflix-cli",
                 "data", "source_portal.jsonc"),
    # user-level override : ~/.config/freeflix/source_portal.jsonc
    os.path.expanduser("~/.config/freeflix/source_portal.jsonc"),
]


def _find_local_override():
    for path in _LOCAL_CANDIDATES:
        if os.path.exists(path):
            return load_local_jsonc(path)
    return {}


# Priority (lowest → highest) :
#   1. DEFAULT_SOURCE_PORTAL  (hardcoded fallback, always correct at ship time)
#   2. remote config          (our repo — lets us patch URLs without a release)
#   3. local override         (user / bundled file — final word)
portals = dict(DEFAULT_SOURCE_PORTAL)
remote_portals = load_remote_jsonc(REMOTE_CONFIG_URL, {})
if remote_portals:
    portals.update(remote_portals)
local_portals = _find_local_override()
if local_portals:
    portals.update(local_portals)
