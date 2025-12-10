###
# Copyright 2016-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###

# -*- coding: utf-8 -*-
"""Debug utilities for iLOrest"""

import json
import os
import logging

try:
    from logging_config_path import get_logging_config_path
except ModuleNotFoundError:
    from ilorest.logging_config_path import get_logging_config_path


def is_debug_enabled(config_path=None):
    """
    Check if debug logging is enabled by reading the logging configuration file.

    Args:
        config_path (str, optional): Path to the logging config file.
                                   Defaults to the standard config location.

    Returns:
        bool: True if debug logging is enabled, False otherwise.
    """
    if config_path is None:
        config_path = get_logging_config_path()

    try:
        # Check if config file exists
        if not os.path.isfile(config_path):
            # If config file doesn't exist, assume debug is disabled
            return False

        # Load the configuration file
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Check the root logger level first
        loggers = config.get("loggers", {})
        root_logger = loggers.get("", {})
        root_level = root_logger.get("level", "INFO").upper()

        # If root logger is set to DEBUG, debug is enabled
        if root_level == "DEBUG":
            return True

        # Check if any specific loggers have DEBUG level
        for logger_name, logger_config in loggers.items():
            if logger_name == "":  # Skip root logger, already checked
                continue
            level = logger_config.get("level", "INFO").upper()
            if level == "DEBUG":
                return True

        # Check handlers for DEBUG level
        handlers = config.get("handlers", {})
        for handler_name, handler_config in handlers.items():
            level = handler_config.get("level", "INFO").upper()
            if level == "DEBUG":
                return True

        # If no DEBUG level found anywhere, debug is disabled
        return False

    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        # If there's any error reading the config, assume debug is disabled
        return False
    except Exception:
        # For any other unexpected error, assume debug is disabled
        return False


def get_current_log_level(logger_name="", config_path=None):
    """
    Get the current log level for a specific logger from the configuration file.

    Args:
        logger_name (str): Name of the logger. Empty string for root logger.
        config_path (str, optional): Path to the logging config file.

    Returns:
        str: The log level (e.g., 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
             Returns 'INFO' as default if not found.
    """
    if config_path is None:
        config_path = get_logging_config_path()

    try:
        # Check if config file exists
        if not os.path.isfile(config_path):
            return "INFO"

        # Load the configuration file
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Get the specific logger configuration
        loggers = config.get("loggers", {})
        logger_config = loggers.get(logger_name, {})

        # Return the level, defaulting to INFO
        return logger_config.get("level", "INFO").upper()

    except Exception:
        # For any error, return INFO as default
        return "INFO"


def set_debug_level_in_config(enable_debug=True, config_path=None):
    """
    Update the logging configuration file to enable or disable debug logging.

    Args:
        enable_debug (bool): True to enable debug, False to disable.
        config_path (str, optional): Path to the logging config file.

    Returns:
        bool: True if successful, False otherwise.
    """
    if config_path is None:
        config_path = get_logging_config_path()

    try:
        # Check if config file exists
        if not os.path.isfile(config_path):
            return False

        # Load the configuration file
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Set the desired level
        new_level = "DEBUG" if enable_debug else "INFO"

        # Update root logger level
        if "loggers" not in config:
            config["loggers"] = {}
        if "" not in config["loggers"]:
            config["loggers"][""] = {}

        config["loggers"][""]["level"] = new_level

        # Update all other loggers to the same level
        for logger_name in config["loggers"]:
            config["loggers"][logger_name]["level"] = new_level

        # Update handlers to the same level
        if "handlers" in config:
            for handler_name in config["handlers"]:
                config["handlers"][handler_name]["level"] = new_level

        # Write the updated configuration back to file
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return True

    except PermissionError as e:
        logging.warning("Administrator privileges are required to save the configuration")
        return False
    except Exception as e:
        logging.debug(f"Unexpected error in set_debug_level_in_config: {e}")
        return False


def set_file_handlers_level(root_logger=None, level=logging.INFO):
    """Set level for any FileHandler-like handlers on the provided logger.

    Args:
        root_logger (logging.Logger): Logger instance to operate on. If None, uses logging.getLogger().
        level (int): Level to set for file handlers.
    Returns:
        int: Number of handlers updated.
    """
    updated = 0
    try:
        if root_logger is None:
            root_logger = logging.getLogger()

        for h in list(root_logger.handlers):
            try:
                if isinstance(h, logging.FileHandler) or getattr(h, "baseFilename", None):
                    h.setLevel(level)
                    updated += 1
            except Exception:
                pass
        return updated
    except Exception:
        return 0


def set_named_handler_level_if_exists(root_logger=None, name="logconfig_stdout", level=logging.INFO):
    """Set level on a named handler only if it exists; do not create handlers.

    Args:
        root_logger (logging.Logger): Logger to operate on (defaults to root logger).
        name (str): Handler name to look for.
        level (int): Level to set.
    Returns:
        bool: True if handler level was updated, False otherwise.
    """
    try:
        if root_logger is None:
            root_logger = logging.getLogger()

        for h in list(root_logger.handlers):
            if getattr(h, "name", None) == name:
                try:
                    h.setLevel(level)
                    return True
                except Exception:
                    return False
        return False
    except Exception:
        return False


def update_config_handlers_levels(config_path=None, level_str="INFO", handler_names=None):
    """Update handler levels in the JSON logging configuration file.

    Args:
        config_path (str): Path to the logging_config.json file.
        level_str (str): Level string to set (e.g., 'DEBUG', 'INFO').
        handler_names (iterable|None): If provided, only update these handler names; otherwise update all handlers.

    Returns:
        bool: True if update succeeded, False otherwise.
    """
    if config_path is None:
        config_path = get_logging_config_path()

    try:
        if not os.path.isfile(config_path):
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        if "handlers" not in config:
            config["handlers"] = {}

        for hname in list(config["handlers"].keys()):
            if handler_names is None or hname in handler_names:
                try:
                    config["handlers"][hname]["level"] = level_str
                except Exception:
                    pass

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return True
    except PermissionError as e:
        logging.warning("Administrator privileges are required to save the configuration")
        return False
    except Exception as e:
        logging.debug(f"Unexpected error in update_config_handlers_levels: {e}")
        return False


def update_config_loggers_levels(config_path=None, level_str="INFO"):
    """Update all logger levels in the JSON logging configuration file.

    Args:
        config_path (str): Path to the logging_config.json file.
        level_str (str): Level string to set for loggers.

    Returns:
        bool: True if update succeeded, False otherwise.
    """
    if config_path is None:
        config_path = get_logging_config_path()

    try:
        if not os.path.isfile(config_path):
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        if "loggers" not in config:
            config["loggers"] = {}

        # Set root logger
        if "" not in config["loggers"]:
            config["loggers"][""] = {}
        config["loggers"][""]["level"] = level_str

        # Set all other loggers to the same level
        for lname in list(config["loggers"].keys()):
            try:
                config["loggers"][lname]["level"] = level_str
            except Exception:
                pass

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return True
    except PermissionError as e:
        logging.warning("Administrator privileges are required to save the configuration")
        return False
    except Exception as e:
        logging.debug(f"Unexpected error in update_config_loggers_levels: {e}")
        return False


def set_runtime_logger_levels(root_logger=None, runtime_level=logging.INFO, set_module_logger=None):
    """Set runtime logger and handler levels consistently.

    Args:
        root_logger (logging.Logger): Logger instance to operate on. Defaults to root logger.
        runtime_level (int): Logging level (e.g., logging.DEBUG).
        set_module_logger (logging.Logger|None): Optional module-level logger to set (e.g., rdmc helper LOGGER).

    Returns:
        bool: True if operations completed (best-effort), False on failure.
    """
    try:
        if root_logger is None:
            root_logger = logging.getLogger()

        root_logger.setLevel(runtime_level)

        # Update named stdout handler if present
        set_named_handler_level_if_exists(root_logger, "logconfig_stdout", runtime_level)

        # Update file handlers level
        set_file_handlers_level(root_logger, runtime_level)

        if set_module_logger is not None:
            try:
                set_module_logger.setLevel(runtime_level)
            except Exception:
                pass

        return True
    except Exception:
        return False


def update_config_file_rotation_settings(config_path=None, max_bytes=None, backup_count=None):
    """Update file rotation settings for RotatingFileHandler in the JSON logging configuration file.

    Args:
        config_path (str): Path to the logging_config.json file.
        max_bytes (int|None): Maximum size of log file in bytes before rotation.
        backup_count (int|None): Number of backup files to keep.

    Returns:
        bool: True if update succeeded, False otherwise.
    """
    if config_path is None:
        config_path = get_logging_config_path()

    try:
        if not os.path.isfile(config_path):
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        if "handlers" not in config:
            config["handlers"] = {}

        # Update rotation settings for RotatingFileHandler instances
        updated = False
        for handler_name, handler_config in config["handlers"].items():
            if not isinstance(handler_config, dict):
                continue

            handler_class = handler_config.get("class", "")
            if "RotatingFileHandler" in handler_class:
                if max_bytes is not None:
                    handler_config["maxBytes"] = max_bytes
                    updated = True

                if backup_count is not None:
                    handler_config["backupCount"] = backup_count
                    updated = True

        if updated:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

        return updated
    except PermissionError as e:
        logging.warning("Administrator privileges are required to save the configuration")
        return False
    except Exception as e:
        logging.debug(f"Unexpected error in update_config_file_rotation_settings: {e}")
        return False


def get_config_file_rotation_settings(config_path=None):
    """Get current file rotation settings from the JSON logging configuration file.

    Args:
        config_path (str): Path to the logging_config.json file.

    Returns:
        dict: Dictionary containing rotation settings for each RotatingFileHandler.
              Format: {handler_name: {'maxBytes': value, 'backupCount': value}}
    """
    if config_path is None:
        config_path = get_logging_config_path()

    rotation_settings = {}

    try:
        if not os.path.isfile(config_path):
            return rotation_settings

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        handlers = config.get("handlers", {})
        for handler_name, handler_config in handlers.items():
            if not isinstance(handler_config, dict):
                continue

            handler_class = handler_config.get("class", "")
            if "RotatingFileHandler" in handler_class:
                rotation_settings[handler_name] = {
                    "maxBytes": handler_config.get("maxBytes"),
                    "backupCount": handler_config.get("backupCount"),
                }

        return rotation_settings
    except Exception:
        return rotation_settings


def validate_rotation_parameters(max_bytes=None, backup_count=None):
    """Validate file rotation parameters.

    Args:
        max_bytes (int|None): Maximum size of log file in bytes before rotation.
        backup_count (int|None): Number of backup files to keep.

    Returns:
        tuple: (is_valid, error_message) where is_valid is bool and error_message is str or None.
    """
    try:
        if max_bytes is not None:
            if not isinstance(max_bytes, int):
                return False, "log_file_size must be an integer"
            if max_bytes <= 0:
                return False, "log_file_size must be a positive integer"

        if backup_count is not None:
            if not isinstance(backup_count, int):
                return False, "backup_count must be an integer"
            if backup_count < 0:
                return False, "backup_count must be a non-negative integer"

        return True, None
    except Exception:
        return False, "Invalid rotation parameters"
