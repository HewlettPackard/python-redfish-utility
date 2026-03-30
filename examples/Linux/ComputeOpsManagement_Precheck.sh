#!/bin/bash
###
#    RESTful Interface Tool Sample Script for HPE iLO Products    #
#  Copyright 2014, 2025 Hewlett Packard Enterprise Development LP #
#                                                                  #
# Description:  ComputeOpsManagement Precheck Validation Script   #
#               Validates JSON configuration files for bulk ops   #
#                                                                  #
#        Firmware support information for this script:            #
#            iLO 5 - Version 2.47 or later                        #
#            iLO 6 - Version 1.64 or later                        #
#            iLO 7 - Version 1.12 or later                        #
###

# Display header function
display_header() {
    echo "================================================================"
    echo "     HPE iLO ComputeOpsManagement Precheck Validator"
    echo "================================================================"
    echo ""
}

# Check if ilorest is available
check_ilorest() {
    if ! command -v ilorest &> /dev/null; then
        echo "ERROR: ilorest command not found in PATH."
        echo "Please ensure HPE iLORest is installed and accessible."
        echo "Download from: https://support.hpe.com/hpesc/public/docDisplay?docId=emr_na-a00105536en_us"
        exit 1
    fi
}

# Validate JSON file exists
validate_json_file() {
    local json_file="$1"
    if [ ! -f "$json_file" ]; then
        echo "ERROR: JSON file '$json_file' not found."
        echo "Please check the file path and try again."
        echo ""
        echo "To generate a template file, use: ComputeOpsManagement_Template.sh"
        exit 1
    fi
}

# Usage function
usage() {
    echo ""
    echo "HPE iLO ComputeOpsManagement Precheck Validator - USAGE"
    echo "======================================================="
    echo ""
    echo "SYNTAX:"
    echo "  $0 <json_file>"
    echo ""
    echo "DESCRIPTION:"
    echo "  Validates a JSON configuration file for ComputeOpsManagement bulk operations."
    echo "  Checks connectivity, credentials, and server compatibility before onboarding."
    echo ""
    echo "REQUIRED PARAMETERS:"
    echo "  json_file           - Path to JSON configuration file containing server list"
    echo ""
    echo "EXAMPLES:"
    echo "  $0 servers.json                    - Validate servers.json file"
    echo "  $0 my_config.json                 - Validate my_config.json file"
    echo "  $0 \"/path/to/servers.json\"        - Validate file with full path"
    echo "  $0 --help                        - Show this help message"
    echo ""
    echo "VALIDATION CHECKS:"
    echo "  - Server connectivity and accessibility"
    echo "  - Credential authentication"
    echo "  - Firmware version compatibility"
    echo "  - ComputeOpsManagement prerequisites"
    echo "  - Activation key format validation"
    echo ""
    echo "NOTES:"
    echo "  - Generate template using ComputeOpsManagement_Template.sh"
    echo "  - Fix any validation errors before running onboarding"
    echo "  - Ensure HPE iLORest is installed and available in system PATH"
    echo ""
    exit 0
}

# Run precheck function
run_precheck() {
    local json_file="$1"

    check_ilorest
    validate_json_file "$json_file"

    echo "Running precheck validation..."
    echo "Configuration file: $json_file"
    echo ""

    ilorest computeopsmanagement multiconnect --input_file "$json_file" --precheck

    if [ $? -eq 0 ]; then
        echo ""
        echo "================================================================"
        echo "Precheck validation PASSED"
        echo "================================================================"
        echo "All servers in the configuration file passed validation."
        echo "You can now proceed with the onboarding operation."
        echo ""
    else
        echo ""
        echo "================================================================"
        echo "Precheck validation FAILED"
        echo "================================================================"
        echo "One or more servers failed validation. Please review the"
        echo "configuration file and error messages above."
        echo ""
        exit 1
    fi
}

# Main script execution
main() {
    display_header

    # Check for help request or missing arguments
    if [ $# -eq 0 ] || [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
        usage
    fi

    # Run precheck validation
    run_precheck "$1"

    echo ""
    echo "Precheck validation completed."
}

# Execute main function
main "$@"
