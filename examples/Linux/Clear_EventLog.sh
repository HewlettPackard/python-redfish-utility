#!/bin/bash

#    RESTful Interface Tool Sample Script for HPE iLO Products    #
#  Copyright 2014, 2020 Hewlett Packard Enterprise Development LP #

# Description:  This is a sample bash script to clear the event   #
#               log on following devices:                         #
#                 Integrated Lights-Out 4 (iLO 4)                 #
#                 Integrated Lights-Out 5 (iLO 5)                 #

#        Firmware support information for this script:            #
#            iLO 5 - All versions.                                #
#            iLO 4 - All versions.                                #

runLocal(){
  ilorest serverlogs --selectlog=IEL --clearlog -u USER_LOGIN -p PASSWORD
  ilorest logout
}

runRemote(){
  ilorest serverlogs --selectlog=IEL --clearlog --url=$1 --user $2 --password $3
  ilorest logout
}

error(){
  echo "Usage:"
  echo        "remote: Clear_EventLog.sh ^<iLO url^> ^<iLO username^>  ^<iLO password^>"
  echo        "local:  Clear_EventLog.sh"
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