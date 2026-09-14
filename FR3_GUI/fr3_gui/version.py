"""Single source of truth for the GUI's version number. Keep in sync with
the firmware's own FIRMWARE_VERSION (board_config.h) whenever either is
bumped, so a user comparing the two (GUI title bar vs. a board's *IDN?
response) always sees matching numbers."""

__version__ = "1.00"
