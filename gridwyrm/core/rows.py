"""Checking name-and-value rows, once rather than twice.

The bands editor and the conditions editor validate the same shape: a name, a
value, a limit, no duplicate names, and a row left blank counts as absent rather
than wrong. Only the value check differs, so that is the argument.
"""


def validate_rows(rows, check_value, limit, value_name, noun,
                  allow_equals=False):
    """Returns (accepted, error message).

    `check_value` takes the raw text and returns the converted value, raising
    ValueError with a reason if it will not do. `value_name` is what the second
    column holds, and `noun` is the plural of what a row is, both only for the
    wording of the messages.
    """
    accepted = []
    for index, (name, value) in enumerate(rows, start=1):
        name = str(name).strip()
        value = str(value).strip()
        if not name and not value:
            continue                             # an untouched row
        if not name:
            return None, "Row %d has no name" % index
        if "=" in name and not allow_equals:
            # Rows are stored as "name = value" lines, so an equals sign in a
            # name would not survive being saved and read back.
            return None, "Row %d: a name cannot contain an equals sign" % index
        if not value:
            return None, "Row %d has no %s" % (index, value_name)
        try:
            converted = check_value(value)
        except ValueError as reason:
            return None, "Row %d: %s" % (index, reason)
        accepted.append((name, converted))

    if not accepted:
        return None, "Give at least one %s" % noun[:-1]
    if len(accepted) > limit:
        return None, "%d %s is as many as stays readable" % (limit, noun)

    seen = {}
    for name, _value in accepted:
        key = name.lower()
        if key in seen:
            return None, "Two %s are both called %s" % (noun, seen[key])
        seen[key] = name
    return accepted, ""
