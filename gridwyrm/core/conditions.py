"""Condition markers: the list, and reading it back."""

from .rows import validate_rows

from .theme import HEX_RE


DEFAULT_CONDITIONS = (
    ("Blind", "#E8B923"),
    ("Charmed", "#E88AA0"),
    ("Deaf", "#5A2E1E"),
    ("Exhausted", "#8B1A1A"),
    ("Frightened", "#FFFFFF"),
    ("Grappled", "#D32027"),
    ("Incapacitated", "#1F3A93"),
    ("Invisible", "#D8E8F0"),
    ("Paralyzed", "#5B2D8E"),
    ("Petrified", "#B8BCC0"),
    ("Poisoned", "#1E7A34"),
    ("Prone", "#2FA8E0"),
    ("Restrained", "#F07818"),
    ("Stunned", "#F0D000"),
    ("Unconscious", "#8C9196"),
)


MAX_CONDITIONS = 20


CONDITION_DEFAULTS_VERSION = 2


SUPERSEDED_CONDITIONS = (
    (("Poisoned", "#4CAF50"), ("Burning", "#E2483D"), ("Frozen", "#4A90E2"),
     ("Blessed", "#F5C542"), ("Cursed", "#9B59B6")),
)


def normalise_conditions(text, version=0):
    """Read the saved conditions, upgrading a list that was never chosen."""
    conditions, _error = parse_conditions(text)
    if not conditions:
        return [list(pair) for pair in DEFAULT_CONDITIONS]
    if version < CONDITION_DEFAULTS_VERSION:
        current = tuple(tuple(pair) for pair in conditions)
        for superseded in SUPERSEDED_CONDITIONS:
            if current == superseded:
                return [list(pair) for pair in DEFAULT_CONDITIONS]
    return [list(pair) for pair in conditions]


def _colour(text):
    if not HEX_RE.match(text):
        raise ValueError("%s is not a six-digit colour" % text)
    return text.upper()


def validate_conditions(rows):
    """Check name and colour pairs from the editor.

    Returns (conditions, error message). Not sorted: the order is the order
    they appear in the picker, and that is the editor's business.
    """
    return validate_rows(rows, _colour, MAX_CONDITIONS, "colour",
                         "conditions")


def format_conditions(conditions):
    return "\n".join("%s = %s" % (name, colour) for name, colour in conditions)


def parse_conditions(text):
    """Read the 'Name = #RRGGBB' lines kept in the settings file."""
    rows = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#") and "=" not in line:
            continue
        name, _, colour = line.partition("=")
        rows.append((name, colour))
    if not rows:
        return None, "nothing to read"
    return validate_conditions(rows)
