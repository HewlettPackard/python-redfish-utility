###
# Copyright 2021-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
###
# -*- coding: utf-8 -*-
"""Configuration resolver for ComputeOpsManagement"""

import json
from ipaddress import ip_address
from typing import Dict, Any, List


class ConfigResolver:
    """Handles configuration file parsing and IP resolution"""

    @staticmethod
    def resolve_ilo_config(config_json_path: str) -> Dict[str, Dict[str, Any]]:
        """Resolve and merge configuration for all iLOs from config file

        :param config_json_path: Path to JSON configuration file
        :type config_json_path: str
        :returns: Dictionary mapping IP addresses to their merged configurations
        :rtype: dict
        """
        with open(config_json_path, "r") as f:
            config_json = json.load(f)

        resolved = {}
        common_settings = config_json.get("commonSettings", {})

        # Extract common settings with type checking
        common_ilo_auth = (
            common_settings.get("iloAuthentication", {})
            if isinstance(common_settings.get("iloAuthentication"), dict)
            else {}
        )
        common_com = (
            common_settings.get("computeOpsManagement", {})
            if isinstance(common_settings.get("computeOpsManagement"), dict)
            else {}
        )
        common_network = common_settings.get("network", {}) if isinstance(common_settings.get("network"), dict) else {}

        common_dns = common_network.get("dns", [])
        common_ntp = common_network.get("ntp", [])
        common_proxy = common_network.get("proxy", {})

        def build_config(ip_str, entry_settings, dns, ntp, skip_dns, skip_ntp, skip_proxy):
            """Build merged configuration for a single IP"""
            entry_ilo_auth = entry_settings.get("iloAuthentication", {})
            entry_com = entry_settings.get("computeOpsManagement", {})
            entry_proxy = entry_settings.get("network", {}).get("proxy", {})

            return {
                "ip": ip_str,
                "username": entry_ilo_auth.get("username") or common_ilo_auth.get("username"),
                "password": entry_ilo_auth.get("password") or common_ilo_auth.get("password"),
                "pcid": entry_com.get("pcid") or common_com.get("pcid"),
                "activationKey": entry_com.get("activationKey") or common_com.get("activationKey"),
                "dns": [] if skip_dns else dns,
                "ntp": [] if skip_ntp else ntp,
                "skipDns": skip_dns,
                "skipNtp": skip_ntp,
                "skipProxy": skip_proxy,
                "proxy": entry_proxy if entry_proxy else common_proxy,
                "auth": entry_ilo_auth if entry_ilo_auth else common_ilo_auth,
            }

        # Process individual entries
        individual_entries = config_json.get("targets", {}).get("ilos", {}).get("individual", [])
        for entry in individual_entries:
            ip = entry["ip"]
            skip_dns = entry.get("skipDns", False)
            skip_ntp = entry.get("skipNtp", False)
            skip_proxy = entry.get("skipProxy", False)
            config = build_config(ip, entry, common_dns, common_ntp, skip_dns, skip_ntp, skip_proxy)
            resolved[ip] = config

        # Process range entries with optimized conversion
        range_entries = config_json.get("targets", {}).get("ilos", {}).get("ranges", [])
        for range_entry in range_entries:
            start_ip = ip_address(range_entry["start"])
            end_ip = ip_address(range_entry["end"])
            skip_dns = range_entry.get("skipDns", False)
            skip_ntp = range_entry.get("skipNtp", False)
            skip_proxy = range_entry.get("skipProxy", False)
            network = range_entry.get("network", {})
            range_dns = [] if skip_dns else network.get("dns", common_dns)
            range_ntp = [] if skip_ntp else network.get("ntp", common_ntp)

            # Optimize: Convert to int once, iterate directly
            start_int = int(start_ip)
            end_int = int(end_ip)
            for ip_int in range(start_int, end_int + 1):
                ip_str = str(ip_address(ip_int))
                config = build_config(ip_str, {}, range_dns, range_ntp, skip_dns, skip_ntp, skip_proxy)
                resolved[ip_str] = config

        return resolved

    @staticmethod
    def extract_target_ips(targets: dict) -> List[Dict[str, Any]]:
        """Extract all target IPs from configuration with validation

        :param targets: targets section from config
        :type targets: dict
        :returns: list of IP information dictionaries
        :rtype: list
        """
        import ipaddress

        target_ips = []
        ilos = targets.get("ilos", {})

        # Process individual IPs
        individual_ilos = ilos.get("individual", [])
        for ilo in individual_ilos:
            ip_info = {"ip": ilo["ip"], "settings": ilo}
            target_ips.append(ip_info)

        # Process IP ranges with size validation
        ranges = ilos.get("ranges", [])
        for range_config in ranges:
            start_ip = ipaddress.IPv4Address(range_config["start"])
            end_ip = ipaddress.IPv4Address(range_config["end"])

            # Validate range size to prevent memory issues
            range_size = int(end_ip) - int(start_ip) + 1
            if range_size > 1000:
                from ilorest.rdmc_helper import InvalidCommandLineError

                raise InvalidCommandLineError(
                    f"IP range {range_config['start']} to {range_config['end']} "
                    f"contains {range_size} IPs. Maximum allowed is 1000 IPs."
                )

            current_ip = start_ip
            while current_ip <= end_ip:
                ip_info = {"ip": str(current_ip), "settings": range_config}
                target_ips.append(ip_info)
                current_ip += 1

        return target_ips
