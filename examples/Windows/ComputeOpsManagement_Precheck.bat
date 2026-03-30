::    RESTful Interface Tool Sample Script for HPE iLO Products    ::
::  Copyright 2014, 2025 Hewlett Packard Enterprise Development LP ::

:: Description:  ComputeOpsManagement Precheck Validation Script   ::
::               Validates JSON configuration files for bulk ops   ::
::                                                                  ::
::        Firmware support information for this script:            ::
::            iLO 5 - Version 2.47 or later                        ::
::            iLO 6 - Version 1.64 or later                        ::
::            iLO 7 - Version 1.12 or later                        ::

@echo off
setlocal enabledelayedexpansion

:: Check if any arguments provided
set argC=0
for %%x in (%*) do Set /A argC+=1

:: Display header
call :display_header

:: Check for help request or missing arguments
if %argC% EQU 0 goto :usage
if "%1"=="help" goto :usage
if "%1"=="-h" goto :usage
if "%1"=="--help" goto :usage

:: Get JSON file parameter
set json_file=%1

::  No additional parameters needed for precheck

goto :run_precheck

:run_precheck
call :check_ilorest
if %errorlevel% neq 0 goto :exit

call :validate_json_file "%json_file%"
if %errorlevel% neq 0 goto :exit

echo Running precheck validation...
echo Configuration file: %json_file%
echo.

ilorest computeopsmanagement multiconnect --input_file "%json_file%" --precheck

if %errorlevel% equ 0 (
    echo.
    echo ================================================================
    echo Precheck validation PASSED
    echo ================================================================
    echo All servers in the configuration file passed validation.
    echo You can now proceed with the onboarding operation.
    echo.
) else (
    echo.
    echo ================================================================
    echo Precheck validation FAILED
    echo ================================================================
    echo One or more servers failed validation. Please review the
    echo configuration file and error messages above.
    echo.
    exit /b 1
)
goto :exit

:usage
echo.
echo HPE iLO ComputeOpsManagement Precheck Validator - USAGE
echo =======================================================
echo.
echo SYNTAX:
echo   %~nx0 ^<json_file^>
echo.
echo DESCRIPTION:
echo   Validates a JSON configuration file for ComputeOpsManagement bulk operations.
echo   Checks connectivity, credentials, and server compatibility before onboarding.
echo.
echo REQUIRED PARAMETERS:
echo   json_file           - Path to JSON configuration file containing server list
echo.
echo EXAMPLES:
echo   %~nx0 servers.json                    - Validate servers.json file
echo   %~nx0 my_config.json                 - Validate my_config.json file
echo   %~nx0 "C:\configs\servers.json"     - Validate file with full path
echo   %~nx0 --help                        - Show this help message
echo.
echo VALIDATION CHECKS:
echo   - Server connectivity and accessibility
echo   - Credential authentication
echo   - Firmware version compatibility
echo   - ComputeOpsManagement prerequisites
echo   - Activation key format validation
echo.
echo NOTES:
echo   - Generate template using ComputeOpsManagement_Template.bat
echo   - Fix any validation errors before running onboarding
echo   - Ensure HPE iLORest is installed and available in system PATH
echo.
goto :exit

:: Error handling function
:check_ilorest
where ilorest >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: ilorest command not found in PATH.
    echo Please ensure HPE iLORest is installed and accessible.
    echo Download from: https://support.hpe.com/hpesc/public/docDisplay?docId=emr_na-a00105536en_us
    exit /b 1
)
exit /b 0

:: Input validation function
:validate_json_file
if not exist "%~1" (
    echo ERROR: JSON file '%~1' not found.
    echo Please check the file path and try again.
    echo.
    echo To generate a template file, use: ComputeOpsManagement_Template.bat
    exit /b 1
)
exit /b 0

:: Display header function
:display_header
echo ================================================================
echo     HPE iLO ComputeOpsManagement Precheck before Onboarding.
echo ================================================================
echo.
exit /b 0

:exit
echo.
echo Precheck validation completed.
if %errorlevel% neq 0 (
    echo Operation failed. Please review the error messages above.
)
pause
