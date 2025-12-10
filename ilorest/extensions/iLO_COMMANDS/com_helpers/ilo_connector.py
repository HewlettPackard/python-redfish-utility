###
# Copyright 2021-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
###
# -*- coding: utf-8 -*-
"""iLO connector module for ComputeOpsManagement"""

import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError, Timeout, RequestException
import time
from typing import Tuple, Optional


class IloConnector:
    """Handles iLO connection and COM onboarding operations"""

    @staticmethod
    def connect_to_com(
        ip: str, username: str, password: str, credential: str, logger, max_retries: int = 3
    ) -> Tuple[bool, Optional[str]]:
        """Enable COM connection on iLO

        :param ip: iLO IP address
        :param username: iLO username
        :param password: iLO password
        :param credential: PCID or activation key
        :param logger: logger instance
        :param max_retries: maximum retry attempts
        :returns: tuple of (success, fail_reason)
        """
        base_url = f"https://{ip}"
        session = requests.Session()
        session.auth = HTTPBasicAuth(username, password)
        session.verify = False

        # Prepare COM enable payload
        payload = {"Oem": {"Hpe": {"CloudConnect": {"CloudConnectEnabled": True, "ActivationKey": credential}}}}

        url = f"{base_url}/redfish/v1/Managers/1/"
        retry_count = 0
        success = False

        while retry_count <= max_retries and not success:
            try:
                logger.info(f"Sending COM enable request to {ip} (attempt {retry_count + 1})")
                response = session.patch(url, json=payload, timeout=30)

                if response.status_code in [200, 202]:
                    success = True
                    logger.info("COM enable request successful")
                else:
                    logger.warning(f"COM enable failed with status {response.status_code}")
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.info(f"Retrying COM enable ({retry_count}/{max_retries})")
                        time.sleep(5)
                    else:
                        return False, "COM enable request failed"

            except (ConnectionError, Timeout, RequestException) as conn_err:
                logger.warning(f"Connection issue during COM enable: {str(conn_err)}")
                if retry_count < max_retries:
                    retry_count += 1
                    logger.info(f"Retrying after connection error ({retry_count}/{max_retries})")
                    time.sleep(15)
                else:
                    logger.error(f"COM enable failed after {max_retries} retries")
                    return False, "Connection failed after retries"

        if not success:
            return False, "COM enable request failed"

        # Wait for connection to complete
        max_wait = 180
        wait_interval = 12
        waited = 0

        logger.info("Waiting for COM connection to complete...")

        while waited < max_wait:
            time.sleep(wait_interval)
            waited += wait_interval

            try:
                response = session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
                if response.status_code == 200:
                    manager_data = response.json()
                    cloud_connect = manager_data.get("Oem", {}).get("Hpe", {}).get("CloudConnect", {})
                    status = cloud_connect.get("CloudConnectStatus", "")
                    fail_reason = cloud_connect.get("FailReason", "")

                    if status == "Connected":
                        logger.info("COM connection successful")
                        return True, None
                    elif status in ["ConnectionFailed", "NotConnected"]:
                        logger.warning(f"COM connection failed: {status}, reason: {fail_reason}")
                        return False, fail_reason if fail_reason else "Connection failed"
                    elif status == "NotEnabled":
                        logger.warning(f"COM not enabled: {fail_reason}")
                        return False, fail_reason if fail_reason else "COM not enabled"
                    else:
                        logger.info(f"COM connection status: {status}, waiting...")

            except (ConnectionError, Timeout, RequestException) as check_err:
                logger.warning(f"Connection issue during status check: {str(check_err)}")
            except Exception as check_err:
                logger.warning(f"Error during status check: {str(check_err)}")

        logger.warning(f"COM connection timed out after {max_wait} seconds")
        return False, "Connection timeout"

    @staticmethod
    def wait_for_ilo_after_reset(ip: str, username: str, password: str, logger, timeout_minutes: int = 3) -> bool:
        """Wait for iLO to come back online after reset

        :param ip: iLO IP address
        :param username: iLO username
        :param password: iLO password
        :param logger: logger instance
        :param timeout_minutes: timeout in minutes
        :returns: True if iLO came back online, False otherwise
        """
        base_url = f"https://{ip}"
        timeout_seconds = timeout_minutes * 60
        check_interval = 10
        max_attempts = int(timeout_seconds / check_interval)
        start_time = time.time()

        logger.info(f"Waiting up to {timeout_minutes} minutes for iLO {ip} to come back online...")

        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    f"{base_url}/redfish/v1/", auth=HTTPBasicAuth(username, password), verify=False, timeout=30
                )

                if response.status_code == 200:
                    elapsed_time = time.time() - start_time
                    logger.info(
                        f"iLO {ip} is back online after {elapsed_time:.1f} seconds "
                        f"(attempt {attempt + 1}/{max_attempts})"
                    )
                    return True

            except (ConnectionError, Timeout):
                pass  # Expected during reset
            except Exception as e:
                logger.warning(f"Unexpected error while waiting for iLO {ip}: {str(e)}")

            if attempt < max_attempts - 1:
                logger.info(
                    f"iLO {ip} still rebooting. Checking again in {check_interval} "
                    f"seconds... (attempt {attempt + 1}/{max_attempts})"
                )
                time.sleep(check_interval)

        elapsed_time = time.time() - start_time
        logger.error(
            f"Timeout: iLO {ip} did not come back online within {timeout_minutes} "
            f"minutes ({elapsed_time:.1f} seconds elapsed)"
        )
        return False

    @staticmethod
    def get_ilo_version(ip: str, username: str, password: str) -> Tuple[float, int]:
        """Get iLO version information

        :param ip: iLO IP address
        :param username: iLO username
        :param password: iLO password
        :returns: tuple of (ilo_version, major_version)
        """
        try:
            base_url = f"https://{ip}"
            response = requests.get(
                f"{base_url}/redfish/v1/Managers/1/", auth=HTTPBasicAuth(username, password), verify=False, timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                fw_version = data.get("FirmwareVersion", "")

                # Parse version string like "iLO 5 v2.47"
                parts = fw_version.split()
                if len(parts) >= 3 and parts[0].lower() == "ilo":
                    major = int(parts[1])
                    version_str = parts[2].lstrip("v").replace(".", "")
                    version = float(f"{major}.{version_str}")
                    return version, major

            # Return default compatible version
            return 5.247, 5

        except Exception:
            return 5.247, 5

    @staticmethod
    def is_pin_onboarding_supported(ilo_version: float, major_version: int) -> bool:
        """Check if PIN-based onboarding is supported

        :param ilo_version: iLO version as float
        :param major_version: iLO major version
        :returns: True if PIN onboarding supported
        """
        # PIN onboarding supported on iLO 6 and iLO 5 >= 2.70
        if major_version >= 6:
            return True
        elif major_version == 5 and ilo_version >= 5.270:
            return True
        return False
