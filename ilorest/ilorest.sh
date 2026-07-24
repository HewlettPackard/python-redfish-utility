#!/bin/sh

FILES="AppToken.dat"
INSTALL_ROOT="/opt/ilorest"
BIN_DIR=$INSTALL_ROOT/bin
VITAL_DIR=$INSTALL_ROOT/vital
DATA_DIR=$INSTALL_ROOT/data
SCRATCH_CONFIG_DIR="/scratch/hpe_ilorest/config"
SCRATCH_CONFIG="$SCRATCH_CONFIG_DIR/logging_config.json"

# Place logging_config.json on the persistent scratch partition so user modifications
# survive ESXi reboots. Only proceed if /scratch is a symlink — ESXi sets it as a
# symlink exclusively when it points to a real persistent disk partition. A plain
# directory means /scratch is ramdisk-backed (volatile), in which case we skip the
# copy to avoid writing to a location that will be lost on reboot.
if [ -L /scratch ]; then
    if [ ! -d "$SCRATCH_CONFIG_DIR" ]; then
        mkdir -p "$SCRATCH_CONFIG_DIR" 2>/dev/null
    fi
    if [ -d "$SCRATCH_CONFIG_DIR" ] && [ ! -e "$SCRATCH_CONFIG" ]; then
        cp $BIN_DIR/logging_config.json.template "$SCRATCH_CONFIG" 2>/dev/null
        chmod +w "$SCRATCH_CONFIG" 2>/dev/null
    fi
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
