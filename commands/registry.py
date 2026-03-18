"""Supported command registry."""

SUPPORTED_COMMANDS = {
    "SET",
    "GET",
    "DEL",
    "EXPIRE",
    "TTL",
}

COMMAND_ARITY = {
    "SET": (3, 3),
    "GET": (2, 2),
    "DEL": (2, 2),
    "EXPIRE": (3, 4),
    "TTL": (2, 2),
}
