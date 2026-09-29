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

# Make the cross-compiled, ilorest-private OpenSSL (libilorestssl.so /
# libilorestcrypto.so, see Makefile.openssl.esxi) discoverable at runtime.
# Neither has a DT_RPATH/DT_RUNPATH baked in, so without this the dynamic
# linker cannot resolve libilorestssl.so's dependency on libilorestcrypto.so
# (fails with "cannot open shared object file").
LD_LIBRARY_PATH="$INSTALL_ROOT/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH

# Enable CNSA 2.0 (post-quantum) TLS defaults for OpenSSL unless the operator has
# already set OPENSSL_CONF or disabled it. This lets `ilorest login` negotiate
# ML-KEM-1024 + ML-DSA-87 with a strict CNSA 2.0 iLO8 natively. See
# ilorest/pqc_openssl_config.py and openssl-cnsa2.cnf.
if [ -z "$OPENSSL_CONF" ] && [ "$ILOREST_DISABLE_PQC_OPENSSL_CONF" != "1" ]; then
    for _cnf in "$SCRIPT_PATH/openssl-cnsa2.cnf" "$INSTALL_ROOT/bin/openssl-cnsa2.cnf" "/etc/ilorest/openssl-cnsa2.cnf"; do
        if [ -f "$_cnf" ]; then
            OPENSSL_CONF="$_cnf"
            export OPENSSL_CONF
            break
        fi
    done
fi

python3 $SCRIPT_PATH/rdmc.py  $@
