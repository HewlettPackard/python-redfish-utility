::    RESTful Interface Tool Sample Script for HPE iLO Products    ::
::  Copyright 2014, 2025 Hewlett Packard Enterprise Development LP ::

:: Description:  ComputeOpsManagement Onboarding Script            ::
::               Onboards multiple iLOs to ComputeOpsManagement    ::
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

:: Parse additional parameters (skip the first argument which is the JSON file)
set reset_flag=
shift
set /a argC-=1

:parse_args
if %argC% GEQ 1 (
    if "%1"=="--allow_ilo_reset" (
        set reset_flag=--allow_ilo_reset
        shift
        set /a argC-=1
        goto parse_args
    )
    echo Warning: Unknown parameter '%1' ignored.
    shift
    set /a argC-=1
    goto parse_args
)

goto :run_onboarding

:run_onboarding
call :check_ilorest
if %errorlevel% neq 0 goto :exit

call :validate_json_file "%json_file%"
if %errorlevel% neq 0 goto :exit

:: Proceeding directly to onboarding (use ComputeOpsManagement_Precheck.bat for validation)
echo Proceeding with onboarding operation...
echo.

:: Display warning if reset is enabled
if defined reset_flag (
    echo ================================================================
    echo WARNING: iLO RESET ENABLED
    echo ================================================================
    echo iLOs may be reset during the onboarding operation if needed.
    echo This may cause temporary network connectivity loss.
    echo.
)

echo ================================================================
echo Starting ComputeOpsManagement Onboarding Operation
echo ================================================================
echo Configuration file: %json_file%
if defined reset_flag echo iLO Reset: ENABLED
echo.

ilorest computeopsmanagement multiconnect --input_file "%json_file%" %reset_flag%

if %errorlevel% equ 0 (
    echo.
    echo ================================================================
    echo ONBOARDING COMPLETED SUCCESSFULLY
    echo ================================================================
    echo All servers have been successfully onboarded to ComputeOpsManagement.
    echo Check the generated report for detailed results.
    echo.
) else (
    echo.
    echo ================================================================
    echo ONBOARDING FAILED
    echo ================================================================
    echo One or more servers failed to onboard. Please review the
    echo error messages above and the generated report for details.
    echo.
    exit /b 1
)
goto :exit

:usage
echo.
echo HPE iLO ComputeOpsManagement Bulk Onboarding Script - USAGE
echo ======================================================
echo.
echo SYNTAX:
echo   %~nx0 ^<json_file^> [options]
echo.
echo DESCRIPTION:
echo   Onboards multiple iLOs to ComputeOpsManagement using a JSON configuration file.
echo   Run ComputeOpsManagement_Precheck.bat first to validate configuration.
echo.
echo REQUIRED PARAMETERS:
echo   json_file           - Path to JSON configuration file containing server list
echo.
echo OPTIONAL PARAMETERS:
echo   --allow_ilo_reset   - Allow iLO reset during onboarding if needed
echo.
echo EXAMPLES:
echo   %~nx0 servers.json                           - Standard onboarding
echo   %~nx0 servers.json --allow_ilo_reset        - Allow iLO resets
echo   %~nx0 "C:\configs\servers.json" --allow_ilo_reset
echo   %~nx0 --help                                - Show this help message
echo.
echo OPERATION FLOW:
echo   1. Validate JSON configuration file
echo   2. Prompt user confirmation if iLO reset is enabled
echo   3. Execute bulk onboarding operation
echo   4. Generate detailed operation report
echo.
echo NOTES:
echo   - Generate template using: ComputeOpsManagement_Template.bat
echo   - Run precheck first using: ComputeOpsManagement_Precheck.bat
echo   - Use --allow_ilo_reset carefully as it may reset iLOs
echo   - Review generated reports for operation details
echo   - Ensure HPE iLORest is installed and available in system PATH
echo.
echo PREREQUISITES:
echo   - Valid JSON configuration file
echo   - Network connectivity to all target iLOs
echo   - Valid credentials for all servers
echo   - ComputeOpsManagement activation keys
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
    echo To validate existing file, use: ComputeOpsManagement_Precheck.bat
    exit /b 1
)
exit /b 0

:: Display header function
:display_header
echo ================================================================
echo     HPE iLO ComputeOpsManagement Onboarding Script
echo ================================================================
echo.
exit /b 0

:exit
echo.
echo Onboarding operation completed.
if %errorlevel% neq 0 (
    echo Operation failed. Please review the error messages above.
)
pause
