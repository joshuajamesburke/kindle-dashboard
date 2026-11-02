#!/bin/sh
# Kill the loop and bring the Kindle reader back.

. "$(dirname "$0")/common.sh"

pkill -f 'bin/start.sh' 2>/dev/null
lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
/etc/init.d/framework start 2>/dev/null || start lab126_gui 2>/dev/null
echo "stopped"
