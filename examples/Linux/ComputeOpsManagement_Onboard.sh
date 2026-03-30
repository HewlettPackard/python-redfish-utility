#!/bin/bash
###
#    RESTful Interface Tool Sample Script for HPE iLO Products    #
#  Copyright 2014, 2025 Hewlett Packard Enterprise Development LP #
#                                                                  #
# Description:  ComputeOpsManagement Onboarding Script            #
#               Onboards multiple iLOs to ComputeOpsManagement    #
#                                                                  #
#        Firmware support information for this script:            #
#            iLO 5 - Version 2.47 or later                        #
#            iLO 6 - Version 1.64 or later                        #
#            iLO 7 - Version 1.12 or later                        #
###

# Display header function
display_header() {
    echo "================================================================"
    echo "     HPE iLO ComputeOpsManagement Onboarding Script"
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
        echo "To validate existing file, use: ComputeOpsManagement_Precheck.sh"
        exit 1
    fi
}

# Usage function
usage() {
    echo ""
    echo "HPE iLO ComputeOpsManagement Onboarding Script - USAGE"
    echo "======================================================"
    echo ""
    echo "SYNTAX:"
    echo "  $0 <json_file> [--allow_ilo_reset]"
    echo ""
    echo "DESCRIPTION:"
    echo "  Onboards multiple iLOs to ComputeOpsManagement using a JSON configuration file."
    echo "  Run ComputeOpsManagement_Precheck.sh first to validate configuration."
    echo ""
    echo "REQUIRED PARAMETERS:"
    echo "  json_file           - Path to JSON configuration file containing server list"
    echo ""
    echo "OPTIONAL PARAMETERS:"
    echo "  --allow_ilo_reset   - Allow iLO reset during onboarding if needed"
    echo ""
    echo "EXAMPLES:"
    echo "  $0 servers.json                           - Standard onboarding"
    echo "  $0 servers.json --allow_ilo_reset        - Allow iLO resets"
    echo "  $0 \"/path/to/servers.json\" --allow_ilo_reset"
    echo "  $0 --help                                - Show this help message"
    echo ""
    echo "OPERATION FLOW:"
    echo "  1. Validate JSON configuration file"
    echo "  2. Prompt user confirmation if iLO reset is enabled"
    echo "  3. Execute bulk onboarding operation"
    echo "  4. Generate detailed operation report"
    echo ""
    echo "NOTES:"
    echo "  - Generate template using: ComputeOpsManagement_Template.sh"
    echo "  - Run precheck first using: ComputeOpsManagement_Precheck.sh"
    echo "  - Use --allow_ilo_reset carefully as it may reset iLOs"
    echo "  - Review generated reports for operation details"
    echo "  - Ensure HPE iLORest is installed and available in system PATH"
    echo ""
    echo "PREREQUISITES:"
    echo "  - Valid JSON configuration file"
    echo "  - Network connectivity to all target iLOs"
    echo "  - Valid credentials for all servers"
    echo "  - ComputeOpsManagement activation keys"
    echo ""
    exit 0
}

# Parse command line arguments
parse_arguments() {
    json_file=""
    reset_flag=""

    # Process arguments
    while [ $# -gt 0 ]; do
        case $1 in
            --help|-h|help)
                usage
                ;;
            --allow_ilo_reset)
                reset_flag="--allow_ilo_reset"
                shift
                ;;
            -*)
                echo "Warning: Unknown parameter '$1' ignored."
                shift
                ;;
            *)
                if [ -z "$json_file" ]; then
                    json_file="$1"
                else
                    echo "Warning: Unknown parameter '$1' ignored."
                fi
                shift
                ;;
        esac
    done

    # Check if JSON file was provided
    if [ -z "$json_file" ]; then
        echo "ERROR: JSON configuration file is required."
        echo ""
        usage
    fi
}

# Run onboarding function
run_onboarding() {
    check_ilorest
    validate_json_file "$json_file"

    # Proceeding directly to onboarding (use ComputeOpsManagement_Precheck.sh for validation)
    echo "Proceeding with onboarding operation..."
    echo ""

    # Display warning if reset is enabled
    if [ -n "$reset_flag" ]; then
        echo "================================================================"
        echo "WARNING: iLO RESET ENABLED"
        echo "================================================================"
        echo "iLOs may be reset during the onboarding operation if needed."
        echo "This may cause temporary network connectivity loss."
        echo ""
    fi

    echo "================================================================"
    echo "Starting ComputeOpsManagement Onboarding Operation"
    echo "================================================================"
    echo "Configuration file: $json_file"
    if [ -n "$reset_flag" ]; then
        echo "iLO Reset: ENABLED"
    fi
    echo ""

    ilorest computeopsmanagement multiconnect --input_file "$json_file" $reset_flag

    if [ $? -eq 0 ]; then
        echo ""
        echo "================================================================"
        echo "ONBOARDING COMPLETED SUCCESSFULLY"
        echo "================================================================"
        echo "All servers have been successfully onboarded to ComputeOpsManagement."
        echo "Check the generated report for detailed results."
        echo ""
    else
        echo ""
        echo "================================================================"
        echo "ONBOARDING FAILED"
        echo "================================================================"
        echo "One or more servers failed to onboard. Please review the"
        echo "error messages above and the generated report for details."
        echo ""
        exit 1
    fi
}

# Main script execution
main() {
    display_header

    # Parse command line arguments
    parse_arguments "$@"

    # Run onboarding operation
    run_onboarding

    echo ""
    echo "Onboarding operation completed."
}

# Execute main function
main "$@"
