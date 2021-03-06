#!/bin/bash

#       RESTful Interface Tool Script for HPE iLO Products        #
#  Copyright 2014, 2020 Hewlett Packard Enterprise Development LP #

# Description:  This is a sample bash script to mount the SPP     #
#               media image, reboot the system, and boot to it.   #

# NOTE:  You will need to replace the                             #
#        http://xx.xx.xx.xx/images/media.iso with the location of #
#        the SPP you want to mount.                               #

#        Firmware support information for this script:            #
#            iLO 5 - All versions                                 #
#            iLO 4 - All versions.                                #
 
runLocal(){
  ilorest virtualmedia 2 http://xx.xx.xx.xx/images/media.iso --bootnextreset --reboot=ForceRestart
  ilorest logout
}

runRemote(){
  ilorest virtualmedia 2 http://xx.xx.xx.xx/images/media.iso --bootnextreset --reboot=ForceRestart --url=$1 --user $2 --password $3
  ilorest logout
}

error(){
  echo "Usage:"
  echo        "remote: Boot_spp.sh ^<iLO url^> ^<iLO username^>  ^<iLO password^>"
  echo        "local:  Boot_spp.sh"
}

if [ "$#" -eq "3" ]
then 
  runRemote "$1" "$2" "$3"
elif [ "$#" -eq "0" ]
then
  runLocal
else
  error
fi