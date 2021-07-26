::    RESTful Interface Tool Sample Script for HPE iLO Products    ::
::  Copyright 2014, 2020 Hewlett Packard Enterprise Development LP ::

:: Description: This a sample batch script to retrieve the HPE SIM ::
::          Single Sign-On (SSO) settings.                         ::

:: NOTE:  You will need to replace the values inside the quotation ::
::        marks with values that are appropriate for your          ::
::        environment.                                             ::

::        HPE SIM Single Sign-On requires iLO Advanced or iLO      ::
::        Select license.                                          ::

::        Firmware support information for this script:            ::
::            iLO 5 - All versions                                 ::
::            iLO 4 - All versions.                                ::


@echo off
set argC=0
for %%x in (%*) do Set /A argC+=1
if %argC% EQU 3 goto :remote
if %argC% EQU 0 goto :local
goto :error

:local
ilorest get SSOsettings --selector=SSO. -u USER_LOGIN -p PASSWORD
ilorest logout
goto :exit
:remote
ilorest get SSOsettings --selector=SSO.  --url %1 --user %2 --password %3
ilorest logout
goto :exit

:error
echo Usage:
echo        remote: Get_SSO_Settings.bat ^<iLO url^> ^<iLO username^>  ^<iLO password^>
echo        local:  Get_SSO_Settings.bat

:exit