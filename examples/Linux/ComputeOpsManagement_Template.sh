#!/bin/bash
###
#    RESTful Interface Tool Sample Script for HPE iLO Products    #
#  Copyright 2014, 2025 Hewlett Packard Enterprise Development LP #
#                                                                  #
# Description:  ComputeOpsManagement Template Generation Script   #
#               Generates JSON template files for bulk operations #
#                                                                  #
#        Firmware support information for this script:            #
#            iLO 5 - Version 2.47 or later                        #
#            iLO 6 - Version 1.64 or later                        #
#            iLO 7 - Version 1.12 or later                        #
###

# Display header function
display_header() {
    echo "================================================================"
    echo "     HPE iLO ComputeOpsManagement Template Generator"
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

# Usage function
usage() {
    echo ""
    echo "HPE iLO ComputeOpsManagement Template Generator - USAGE"
    echo "======================================================"
    echo ""
    echo "SYNTAX:"
    echo "  $0 [template_filename]"
    echo ""
    echo "DESCRIPTION:"
    echo "  Generates a JSON template file for ComputeOpsManagement bulk operations."
    echo "  The template contains the required structure for server configurations."
    echo ""
    echo "PARAMETERS:"
    echo "  template_filename   - Optional custom filename for the template"
    echo "                       (default: multiconnect_input_template.json)"
    echo ""
    echo "EXAMPLES:"
    echo "  $0                           - Generate default template file"
    echo "  $0 my_servers.json          - Generate template with custom filename"
    echo "  $0 --help                   - Show this help message"
    echo ""
    echo "NOTES:"
    echo "  - Edit the generated template file with your server details"
    echo "  - Include iLO IP addresses, credentials, and activation keys"
    echo "  - Use the template with precheck and onboard scripts"
    echo "  - Ensure HPE iLORest is installed and available in system PATH"
    echo ""
    exit 0
}

# Generate template function
generate_template() {
    local template_file="$1"

    check_ilorest

    echo "Generating JSON template file..."
    ilorest computeopsmanagement multiconnect --input_file_json_template

    if [ $? -eq 0 ]; then
        if [ -n "$template_file" ] && [ "$template_file" != "multiconnect_input_template.json" ]; then
            if [ -f "multiconnect_input_template.json" ]; then
                mv "multiconnect_input_template.json" "$template_file"
                echo "Template file '$template_file' created successfully."
            else
                echo "Error: Template file was not created."
                exit 1
            fi
        else
            echo "Template file 'multiconnect_input_template.json' created successfully."
        fi
        echo "You can now edit this file with your server details and credentials."
    else
        echo "Error generating template file."
        exit 1
    fi
}

# Main script execution
main() {
    display_header

    # Check for help request
    if [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
        usage
    fi

    # Generate template with optional custom filename
    generate_template "$1"

    echo ""
    echo "Template generation completed."
}

# Execute main function
main "$@"
