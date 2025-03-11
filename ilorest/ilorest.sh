#!/bin/sh

FILES="AppToken.dat"
INSTALL_ROOT="/opt/ilorest"
VITAL_DIR=$INSTALL_ROOT/vital
DATA_DIR=$INSTALL_ROOT/data
for f in $FILES; do
   if [ ! -e $VITAL_DIR/$f ]; then
      sh -cx "
         cp $DATA_DIR/$f $VITAL_DIR/$f
         chmod +w $VITAL_DIR/$f
      " >/dev/null 2>&1
   fi
done

SCRIPT_PATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
python3 $SCRIPT_PATH/rdmc.py $@
