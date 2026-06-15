"""Command manifest loader + validator for the Kodi addon.

Reads resources/commands.json and validates incoming command params against
the declared schema. Lightweight — no jsonschema dependency (Kodi addons
ship without extra deps), just the bits we actually need.
"""

import json
import os


_PARAM_ALIASES = {
    "mute": {"muted": "mute"},
}


class ValidationError(Exception):
    pass


def load_manifest():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "commands.json")
    with open(path) as f:
        return json.load(f)


def normalize_params(command, params):
    """Apply known aliases (e.g. 'muted' -> 'mute'). Returns a new dict."""
    if params is None:
        return {}
    aliases = _PARAM_ALIASES.get(command, {})
    out = {}
    for k, v in params.items():
        out[aliases.get(k, k)] = v
    return out


def validate(manifest, command, params):
    """Raise ValidationError on missing required params or bad enums.

    Unknown params are tolerated (forward-compat).
    """
    schema = manifest.get("commands", {}).get(command)
    if schema is None:
        raise ValidationError("unknown command: {}".format(command))

    declared = schema.get("params", {}) or {}
    norm = normalize_params(command, params)

    for pname, pschema in declared.items():
        if pschema.get("required") and pname not in norm:
            raise ValidationError(
                "{}: missing required param '{}'".format(command, pname)
            )
        if pname in norm:
            val = norm[pname]
            enum = pschema.get("enum")
            if enum and val not in enum:
                raise ValidationError(
                    "{}: param '{}' must be one of {}; got {!r}".format(
                        command, pname, enum, val
                    )
                )
            ptype = pschema.get("type")
            if ptype == "integer" and not isinstance(val, int):
                try:
                    norm[pname] = int(val)
                except (TypeError, ValueError):
                    raise ValidationError(
                        "{}: param '{}' must be integer; got {!r}".format(
                            command, pname, val
                        )
                    )
            elif ptype == "boolean" and not isinstance(val, bool):
                if isinstance(val, str) and val.lower() in ("true", "false"):
                    norm[pname] = (val.lower() == "true")
                else:
                    raise ValidationError(
                        "{}: param '{}' must be boolean; got {!r}".format(
                            command, pname, val
                        )
                    )
            elif ptype == "string" and not isinstance(val, str):
                raise ValidationError(
                    "{}: param '{}' must be string; got {!r}".format(
                        command, pname, val
                    )
                )
    return norm
