::    RESTful Interface Tool Sample Script for HPE iLO Products    ::
::  Copyright 2014, 2025 Hewlett Packard Enterprise Development LP ::

:: Description:  ComputeOpsManagement Template Generation Script    ::
::               Generates JSON template files for bulk operations  ::
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

:: Check for help request
if %argC% EQU 0 goto :generate_template
if "%1"=="help" goto :usage
if "%1"=="-h" goto :usage
if "%1"=="--help" goto :usage

:: If filename is provided, use it as output filename
if %argC% EQU 1 (
    set template_file=%1
    goto :generate_template_custom
)

goto :usage

:generate_template
call :check_ilorest
if %errorlevel% neq 0 goto :exit
echo Generating JSON template file...
ilorest computeopsmanagement multiconnect --input_file_json_template
if %errorlevel% equ 0 (
    echo Template file 'multiconnect_input_template.json' created successfully.
    echo You can now edit this file with your server details and credentials.
) else (
    echo Error generating template file.
    exit /b 1
)
goto :exit

:generate_template_custom
call :check_ilorest
if %errorlevel% neq 0 goto :exit
echo Generating JSON template file: %template_file%
ilorest computeopsmanagement multiconnect --input_file_json_template
if %errorlevel% equ 0 (
    if exist "multiconnect_input_template.json" (
        move "multiconnect_input_template.json" "%template_file%"
        echo Template file '%template_file%' created successfully.
        echo You can now edit this file with your server details and credentials.
    ) else (
        echo Error: Template file was not created.
        exit /b 1
    )
) else (
    echo Error generating template file.
    exit /b 1
)
goto :exit

:usage
echo.
echo HPE iLO ComputeOpsManagement Template Generator - USAGE
echo ======================================================
echo.
echo SYNTAX:
echo   %~nx0 [template_filename]
echo.
echo DESCRIPTION:
echo   Generates a JSON template file for ComputeOpsManagement bulk operations.
echo   The template contains the required structure for server configurations.
echo.
echo PARAMETERS:
echo   template_filename   - Optional custom filename for the template
echo                        (default: multiconnect_input_template.json)
echo.
echo EXAMPLES:
echo   %~nx0                           - Generate default template file
echo   %~nx0 my_servers.json          - Generate template with custom filename
echo   %~nx0 --help                   - Show this help message
echo.
echo NOTES:
echo   - Edit the generated template file with your server details
echo   - Include iLO IP addresses, credentials, and activation keys
echo   - Use the template with precheck and onboard scripts
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

:: Display header function
:display_header
echo ================================================================
echo     HPE iLO ComputeOpsManagement Template Generator
echo ================================================================
echo.
exit /b 0

:exit
echo.
echo Template generation completed.
if %errorlevel% neq 0 (
    echo Operation failed. Please check the error messages above.
)
pause
