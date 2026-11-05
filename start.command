#!/bin/sh
# macOS: double-click this file in Finder to start the travel photo tool.
# The first time, right-click it and choose "Open" if macOS asks for confirmation.
# All the work is in start.sh; see docs/decisions/0007-one-click-launcher.md.
cd "$(dirname "$0")" || exit 1
TRAVELPHOTOS_IN_TERMINAL=1 exec /bin/sh ./start.sh "$@"
