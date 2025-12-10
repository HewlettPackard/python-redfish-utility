###
# Copyright 2021-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
###
# -*- coding: utf-8 -*-
"""Network configuration module for ComputeOpsManagement"""

from requests.exceptions import ConnectionError, Timeout, RequestException
from typing import Optional, Tuple


class NetworkConfigurator:
    """Handles DNS, NTP, and Proxy configuration for iLOs"""

    @staticmethod
    def configure_dns(session, base_url: str, dns_servers: list, logger) -> None:
        """Configure DNS servers on iLO

        :param session: requests Session object
        :param base_url: base URL for iLO
        :param dns_servers: list of DNS servers
        :param logger: logger instance
        """
        try:
            # Check if already configured
            current_dns = NetworkConfigurator.get_current_dns_servers(session, base_url)

            if current_dns is not None:
                desired_dns = sorted([srv.strip() for srv in dns_servers if srv and srv.strip()])
                current_dns_sorted = sorted([srv.strip() for srv in current_dns if srv and srv.strip()])

                if desired_dns == current_dns_sorted:
                    logger.info(f"DNS servers already configured as desired: {desired_dns}")
                    return

            # Separate IPv4 and IPv6 DNS servers
            ipv4_dns = []
            ipv6_dns = []

            for dns_server in dns_servers:
                if dns_server:
                    dns_clean = dns_server.strip()
                    if dns_clean:
                        if NetworkConfigurator._is_ipv6_address(dns_clean):
                            ipv6_dns.append(dns_clean)
                        else:
                            ipv4_dns.append(dns_clean)

            # Configure via EthernetInterfaces endpoint
            dns_config_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces/1"

            payload = {
                "DHCPv4": {"UseDNSServers": False},
                "DHCPv6": {"UseDNSServers": False},
                "Oem": {
                    "Hpe": {
                        "DHCPv4": {"UseDNSServers": False},
                        "DHCPv6": {"UseDNSServers": False},
                        "IPv4": {"DNSServers": ipv4_dns},
                        "IPv6": {"DNSServers": ipv6_dns},
                    }
                },
            }

            response = session.patch(dns_config_url, json=payload, timeout=30)
            if response.status_code in [200, 204]:
                logger.info(f"Successfully configured DNS servers: {dns_servers}")
            else:
                raise Exception(f"Failed to configure DNS. HTTP {response.status_code}")

        except Exception as e:
            logger.error(f"Error configuring DNS: {str(e)}")
            raise

    @staticmethod
    def configure_ntp(session, base_url: str, ntp_servers: list, allow_ilo_reset: bool, logger) -> Tuple[bool, bool]:
        """Configure NTP servers on iLO

        :param session: requests Session object
        :param base_url: base URL for iLO
        :param ntp_servers: list of NTP servers
        :param allow_ilo_reset: allow iLO reset if needed
        :param logger: logger instance
        :returns: tuple of (ilo_was_reset, needs_reset)
        """
        ilo_was_reset = False
        needs_reset = False
        dhcp_disabled = False

        try:
            # Check if already configured
            current_ntp = NetworkConfigurator.get_current_ntp_servers(session, base_url)

            if current_ntp is not None:
                desired_ntp = sorted([srv.strip() for srv in ntp_servers if srv and srv.strip()])
                current_ntp_sorted = sorted([srv.strip() for srv in current_ntp if srv and srv.strip()])

                if desired_ntp == current_ntp_sorted:
                    logger.info(f"NTP servers already configured as desired: {desired_ntp}")
                    return ilo_was_reset, needs_reset

            # Try to disable DHCP NTP if needed
            eth_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces"

            try:
                eth_response = session.get(eth_url, timeout=30)
                if eth_response.status_code == 200:
                    members = eth_response.json().get("Members", [])

                    for member in members:
                        interface_url = base_url + member.get("@odata.id", "")
                        try:
                            iface_resp = session.get(interface_url, timeout=30)
                            if iface_resp.status_code == 200:
                                iface_data = iface_resp.json()
                                if iface_data.get("Status", {}).get("State") == "Enabled":
                                    # Check if DHCP NTP already disabled
                                    dhcpv4_ntp = iface_data.get("DHCPv4", {}).get("UseNTPServers", False)
                                    dhcpv6_ntp = iface_data.get("DHCPv6", {}).get("UseNTPServers", False)

                                    if not dhcpv4_ntp and not dhcpv6_ntp:
                                        logger.info("DHCP NTP already disabled")
                                        dhcp_disabled = True
                                        break

                                    # Disable DHCP NTP
                                    dhcp_payload = {
                                        "DHCPv4": {"UseNTPServers": False},
                                        "DHCPv6": {"UseNTPServers": False},
                                        "Oem": {
                                            "Hpe": {
                                                "DHCPv4": {"UseNTPServers": False},
                                                "DHCPv6": {"UseNTPServers": False},
                                            }
                                        },
                                    }

                                    dhcp_resp = session.patch(interface_url, json=dhcp_payload, timeout=30)
                                    if dhcp_resp.status_code in [200, 204]:
                                        logger.info("Successfully disabled DHCP NTP")
                                        dhcp_disabled = True
                                        break
                        except (ConnectionError, Timeout, RequestException):
                            logger.warning("Connection error accessing interface - may already be disabled")
                            dhcp_disabled = True  # Assume already disabled
                            break
            except (ConnectionError, Timeout, RequestException):
                logger.warning("Connection error accessing interfaces - proceeding anyway")
                dhcp_disabled = True  # Assume already disabled

            # Configure static NTP servers
            ntp_url = f"{base_url}/redfish/v1/Managers/1/DateTime"
            ntp_list = list(ntp_servers)
            if len(ntp_list) == 1:
                ntp_list.append("")

            payload = {"StaticNTPServers": ntp_list}
            response = session.patch(ntp_url, json=payload, timeout=30)

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to configure NTP. HTTP {response.status_code}")

            logger.info(f"Successfully configured NTP servers: {ntp_servers}")

            # Reset if allowed
            if allow_ilo_reset:
                reset_url = f"{base_url}/redfish/v1/Managers/1/Actions/Manager.Reset"
                reset_payload = {"ResetType": "GracefulRestart"}
                reset_resp = session.post(reset_url, json=reset_payload, timeout=30)
                if reset_resp.status_code in [200, 202, 204]:
                    logger.info("iLO reset initiated for NTP configuration")
                    ilo_was_reset = True
            else:
                needs_reset = True

        except Exception as e:
            logger.error(f"Error configuring NTP: {str(e)}")
            raise

        return ilo_was_reset, needs_reset

    @staticmethod
    def get_current_dns_servers(session, base_url: str) -> Optional[list]:
        """Get current DNS configuration from iLO"""
        try:
            dns_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces/1"
            response = session.get(dns_url, timeout=30)

            if response.status_code == 200:
                data = response.json()
                oem_hpe = data.get("Oem", {}).get("Hpe", {})
                ipv4_dns = oem_hpe.get("IPv4", {}).get("DNSServers", [])
                ipv6_dns = oem_hpe.get("IPv6", {}).get("DNSServers", [])

                # Use list comprehension for efficiency
                return [srv for srv in ipv4_dns + ipv6_dns if srv]
            return None
        except Exception:
            return None

    @staticmethod
    def get_current_ntp_servers(session, base_url: str) -> Optional[list]:
        """Get current NTP configuration from iLO"""
        try:
            ntp_url = f"{base_url}/redfish/v1/Managers/1/DateTime"
            response = session.get(ntp_url, timeout=30)

            if response.status_code == 200:
                data = response.json()
                ntp_servers = data.get("StaticNTPServers", [])
                return [srv for srv in ntp_servers if srv]
            return None
        except Exception:
            return None

    @staticmethod
    def _is_ipv6_address(address: str) -> bool:
        """Check if address is IPv6"""
        return ":" in address
