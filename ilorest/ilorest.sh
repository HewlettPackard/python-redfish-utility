#!/bin/sh
SCRIPT_PATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
python3 $SCRIPT_PATH/rdmc.py $@
