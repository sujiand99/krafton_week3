"""Supported command registry."""

SUPPORTED_COMMANDS = {
    "SET",
    "GET",
    "DEL",
    "EXPIRE",
    "TTL",
    "RESERVE_SEAT",
    "CONFIRM_SEAT",
    "FORCE_CONFIRM_SEAT",
    "RELEASE_SEAT",
    "SEAT_STATUS",
    "JOIN_QUEUE",
    "QUEUE_POSITION",
    "POP_QUEUE",
    "LEAVE_QUEUE",
    "PEEK_QUEUE",
}

COMMAND_ARITY = {
    "SET": (3, 3),
    "GET": (2, 2),
    "DEL": (2, 2),
    "EXPIRE": (3, 4),
    "TTL": (2, 2),
    "RESERVE_SEAT": (5, 5),
    "CONFIRM_SEAT": (4, 4),
    "FORCE_CONFIRM_SEAT": (4, 4),
    "RELEASE_SEAT": (4, 4),
    "SEAT_STATUS": (3, 3),
    "JOIN_QUEUE": (3, 3),
    "QUEUE_POSITION": (3, 3),
    "POP_QUEUE": (2, 2),
    "LEAVE_QUEUE": (3, 3),
    "PEEK_QUEUE": (2, 2),
}
