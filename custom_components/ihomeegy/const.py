"""Constants for the iHomeegy integration."""

from __future__ import annotations

DOMAIN = "ihomeegy"
MANUFACTURER = "iHomeegy"

# Config entry data
CONF_UNIT_ID = "unit_id"
CONF_KEY = "key"  # this Home Assistant's own 32-byte member key (hex), made when the invite was accepted
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"

DEFAULT_PORT = 8890
ZEROCONF_TYPE = "_ihomenoise._tcp.local."

# The unit's local protocol (firmware ih_net_noise.h / ih_noise.h)
NOISE_PROTOCOL = b"Noise_NNpsk0_25519_ChaChaPoly_SHA256"
NOISE_PROLOGUE = b"iHome/noise/v1"
MAX_PLAIN_TO_UNIT = 2048  # the unit refuses bigger messages

# The unit sends {"t":"ping"} after 10 s of silence and closes after 30 s; the app gives up after 25 s.
SILENCE_LIMIT = 25.0

# {"t":"bye","code":...}
BYE_REMOVED = 4001  # this member was removed from the unit
BYE_NEW_INVITE = 4002  # this member got a new invite (its key was replaced)

INVITE_PREFIX = "ihome://join?d="
