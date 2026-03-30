#!/bin/sh

FILES="AppToken.dat"
INSTALL_ROOT="/opt/ilorest"
BIN_DIR=$INSTALL_ROOT/bin
VITAL_DIR=$INSTALL_ROOT/vital
DATA_DIR=$INSTALL_ROOT/data

# Copy logging config from bin (read-only) to /opt/ilorest/ (writable)
if [ ! -e $INSTALL_ROOT/logging_config.json ]; then
    cp $BIN_DIR/logging_config.json.template $INSTALL_ROOT/logging_config.json 2>/dev/null
    chmod +w $INSTALL_ROOT/logging_config.json 2>/dev/null
fi

for f in $FILES; do
   if [ ! -e $VITAL_DIR/$f ]; then
      sh -cx "
         cp $DATA_DIR/$f $VITAL_DIR/$f
         chmod +w $VITAL_DIR/$f
      " >/dev/null 2>&1
   fi
done

SCRIPT_PATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
python3 $SCRIPT_PATH/rdmc.py  $@
