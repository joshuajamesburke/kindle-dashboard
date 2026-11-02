#!/bin/sh
# Draw one frame and stop. Does not touch the Kindle UI, does not suspend.
# This is the safe way to test - errors stay readable and the device
# remains usable.

. "$(dirname "$0")/common.sh"

housekeep

python3 "$ROOT/bin/run.py"
echo "exit: $?"
