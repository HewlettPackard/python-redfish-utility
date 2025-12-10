###
# Copyright 2025 Hewlett Packard Enterprise, Inc. All rights reserved.
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
"""Command for configuring logging options"""
import json
import logging
import logging.config
import os

try:
    # Try top-level imports first (VMware packaging, flattened installs)
    from rdmc_helper import LOGGER, InvalidCommandLineError, ReturnCodes
    from logging_config_path import get_logging_config_path
    from debug_utils import (
        set_file_handlers_level,
        set_named_handler_level_if_exists,
        update_config_handlers_levels,
        update_config_loggers_levels,
        set_runtime_logger_levels,
        update_config_file_rotation_settings,
        get_config_file_rotation_settings,
        validate_rotation_parameters,
    )
except ImportError:
    # Fallback to package-qualified imports (standard pip/development installs)
    from ilorest.rdmc_helper import LOGGER, InvalidCommandLineError, ReturnCodes
    from ilorest.logging_config_path import get_logging_config_path
    from ilorest.debug_utils import (
        set_file_handlers_level,
        set_named_handler_level_if_exists,
        update_config_handlers_levels,
        update_config_loggers_levels,
        set_runtime_logger_levels,
        update_config_file_rotation_settings,
        get_config_file_rotation_settings,
        validate_rotation_parameters,
    )


class LogconfigCommand:
    """Command to configure logging options"""

    def __init__(self):
        self.ident = {
            "name": "logconfig",
            "usage": None,
            "description": (
                "Configure logging options for iLOREST\n\n\t"
                "Example:\n\tilorest logconfig --enable-debug --logdir=/custom/path\n\t"
                'ilorest logconfig --logdir="C:\\path with spaces"\n\t'
                "ilorest logconfig --enable-debug\n\t"
                "ilorest logconfig --disable-debug\n\t"
                "ilorest logconfig --log_file_size=5MB --log_retention_count=5\n\t"
                "ilorest logconfig --log_file_size=10MB --log_retention_count=3\n\t"
                "ilorest logconfig --show"
            ),
            "summary": "Configure logging options such as debug mode, log directory, and file rotation.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.logging_config_path = get_logging_config_path()

    def parse_file_size(self, size_str):
        """Parse file size string in MB format only

        :param size_str: size string (e.g., "5MB", "10mb", "1.5MB")
        :type size_str: str
        :returns: size in bytes
        :rtype: int
        :raises InvalidCommandLineError: if the size format is invalid
        """
        if not isinstance(size_str, str):
            size_str = str(size_str)
        size_str = size_str.strip().upper()

        # Check if it ends with MB
        if size_str.endswith("MB"):
            try:
                mb_value = float(size_str[:-2])
                if mb_value <= 0:
                    raise InvalidCommandLineError("File size must be a positive number")
                return int(mb_value * 1024 * 1024)  # Convert MB to bytes
            except ValueError:
                raise InvalidCommandLineError("Invalid MB format. Use format like '5MB' or '1.5MB'")
        else:
            # Only MB format is supported
            raise InvalidCommandLineError("Invalid file size format. Use MB format only (e.g., 5MB, 10MB, 1.5MB)")

    def load_logging_config(self):
        """Load logging configuration from JSON file

        :returns: dict containing logging configuration
        """
        try:
            if os.path.exists(self.logging_config_path):
                with open(self.logging_config_path, "r") as config_file:
                    return json.load(config_file)
            else:
                # Return default configuration if file doesn't exist
                return {"debug": False, "logdir": None}
        except (json.JSONDecodeError, IOError) as ex:
            LOGGER.warning(f"Failed to load logging config: {str(ex)}. Using defaults.")
            return {"debug": False, "logdir": None}

    def save_logging_config(self, config_data):
        """Save logging configuration to JSON file

        :param config_data: dictionary containing configuration to save
        :type config_data: dict
        """
        try:
            # Ensure directory exists
            config_dir = os.path.dirname(self.logging_config_path)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)

            with open(self.logging_config_path, "w") as config_file:
                json.dump(config_data, config_file, indent=2)

            LOGGER.info(f"Logging configuration saved to: {self.logging_config_path}")
        except IOError as ex:
            raise InvalidCommandLineError(f"Failed to save logging config: {str(ex)}")

    def update_logging_config_value(self, key, value):
        """Update a specific value in the logging configuration file

        :param key: configuration key to update
        :type key: str
        :param value: new value for the configuration key
        :type value: any
        :raises InvalidCommandLineError: if the key is not present in logging configuration
        """
        # Load current configuration
        logging_config = self.load_logging_config()

        # Check if the key exists in the configuration
        if key not in logging_config:
            raise InvalidCommandLineError(
                f"Configuration parameter '{key}' not found in logging configuration file. "
                f"Please ensure the parameter is defined in {self.logging_config_path}"
            )

        # Update the specific key
        logging_config[key] = value

        # Save updated configuration
        self.save_logging_config(logging_config)

        LOGGER.info(f"Updated logging config: {key} = {value}")

    def update_logging_config_logdir(self, logdir_path):
        """Update log directory in the logging configuration file and apply to handlers

        :param logdir_path: new log directory path
        :type logdir_path: str
        """
        # Use the load/save helpers so behavior is consistent with other updates
        try:
            config_data = self.load_logging_config()

            # Ensure config_data is a dict
            if not isinstance(config_data, dict):
                raise InvalidCommandLineError("Loaded logging config is not a JSON object")

            # Store the logdir exactly as provided by the user
            config_data["logdir"] = logdir_path

            # Update file handler paths if they exist.
            # Preserve template-style filenames that use '%(logdir)s' so runtime
            # substitution still works. For handlers with hardcoded absolute
            # paths, move only the basename into the new directory.
            handlers = config_data.get("handlers", {})
            for handler_name, handler_config in handlers.items():
                if not isinstance(handler_config, dict):
                    continue

                # Only consider handlers that have a 'filename' key or are FileHandlers
                original_filename = handler_config.get("filename")
                if original_filename:
                    try:
                        if "%(logdir)s" in original_filename:
                            # Leave template intact; runtime will substitute using config['logdir']
                            pass
                        else:
                            # Replace directory part, keep basename
                            filename_only = os.path.basename(original_filename)
                            handler_config["filename"] = os.path.join(logdir_path, filename_only)
                    except Exception:
                        # skip modifying the handler if something goes wrong
                        continue

            # Persist using the command's save helper (handles directories and errors)
            self.save_logging_config(config_data)

            # Try to apply to current session (best-effort)
            # First ensure the log directory exists and resolve template variables
            try:
                # Create the directory if it doesn't exist (for immediate session application)
                resolved_logdir = os.path.abspath(logdir_path) if not os.path.isabs(logdir_path) else logdir_path
                if not os.path.exists(resolved_logdir):
                    os.makedirs(resolved_logdir, exist_ok=True)
                # Create a copy of config for immediate application with resolved template variables
                session_config = json.loads(json.dumps(config_data))  # Deep copy
                # Replace %(logdir)s template with actual path in all handlers
                for handler_name, handler_config in session_config.get("handlers", {}).items():
                    if isinstance(handler_config, dict) and "filename" in handler_config:
                        filename = handler_config["filename"]
                        if "%(logdir)s" in filename:
                            # Replace template with actual resolved path
                            handler_config["filename"] = filename.replace("%(logdir)s", resolved_logdir)
                logging.config.dictConfig(session_config)
                LOGGER.info(f"Applied new log directory configuration: {logdir_path}")
            except Exception as ex:
                LOGGER.warning(f"Failed to apply logging config to current session: {str(ex)}")

            LOGGER.info(f"Updated log directory in configuration: {logdir_path}")

        except InvalidCommandLineError:
            # Re-raise known command errors
            raise
        except Exception as ex:
            raise InvalidCommandLineError(f"Failed to update log directory in config: {str(ex)}")

    def update_logging_config_levels(self, debug_enabled):
        """Update logging levels in the logging configuration file

        :param debug_enabled: whether debug logging should be enabled
        :type debug_enabled: bool
        """
        try:
            log_level = "DEBUG" if debug_enabled else "INFO"

            # Update persistent configuration for handlers and loggers.
            # Track update success and return False to caller if any write/update failed.
            success = True

            try:
                if debug_enabled:
                    # Set file handler to DEBUG to capture both debug and info logs
                    success = success and bool(
                        update_config_handlers_levels(self.logging_config_path, "DEBUG", handler_names=["file"])
                    )
                    # Set stdout to WARNING to keep console clean
                    success = success and bool(
                        update_config_handlers_levels(self.logging_config_path, "CRITICAL", handler_names=["stdout"])
                    )
                    success = success and bool(update_config_loggers_levels(self.logging_config_path, "DEBUG"))

                    if not success:
                        # caller displays warning
                        return False

                    # Apply runtime levels: root logger at DEBUG but ensure stdout handler remains WARNING
                    root_logger = logging.getLogger()
                    # Set module/root loggers to DEBUG
                    set_runtime_logger_levels(root_logger, logging.DEBUG, set_module_logger=LOGGER)
                    # Ensure stdout handler (if present) is left at CRITICAL
                    set_named_handler_level_if_exists(root_logger, "logconfig_stdout", logging.CRITICAL)
                    # Ensure file handlers accept DEBUG
                    set_file_handlers_level(root_logger, logging.DEBUG)
                else:
                    # Turning debug off: set file handler to INFO, stdout to WARNING
                    success = success and bool(
                        update_config_handlers_levels(self.logging_config_path, "INFO", handler_names=["file"])
                    )
                    success = success and bool(
                        update_config_handlers_levels(self.logging_config_path, "CRITICAL", handler_names=["stdout"])
                    )
                    success = success and bool(
                        update_config_handlers_levels(self.logging_config_path, "ERROR", handler_names=["stderr"])
                    )
                    success = success and bool(update_config_loggers_levels(self.logging_config_path, "INFO"))

                    if not success:
                        # caller displays warning
                        return False

                    root_logger = logging.getLogger()
                    set_runtime_logger_levels(root_logger, logging.INFO, set_module_logger=LOGGER)
                    # Ensure stdout handler stays at CRITICAL
                    set_named_handler_level_if_exists(root_logger, "logconfig_stdout", logging.CRITICAL)
                    # Set file handlers to INFO
                    set_file_handlers_level(root_logger, logging.INFO)

                LOGGER.info(f"Updated logging configuration: levels set to {log_level}")
            except Exception:
                # Runtime application failed, but config file updates may have succeeded.
                LOGGER.debug("Failed to update runtime handler levels after saving config")
                # We consider runtime application failures non-fatal for persistence; return True
                return True

            return True
        except (json.JSONDecodeError, IOError) as ex:
            # JSON IO exceptions are considered as failures to persist configuration
            LOGGER.debug(f"Failed to update logging config due to JSON/IO error: {str(ex)}")
            return False

    def update_logging_config_file_rotation(self, max_bytes=None, backup_count=None):
        """Update file rotation settings in the logging configuration file

        :param max_bytes: maximum size of log file in bytes before rotation
        :type max_bytes: int
        :param backup_count: number of log files to retain during rotation (log retention count)
        :type backup_count: int
        """
        try:
            # Use the utility function to update rotation settings
            success = update_config_file_rotation_settings(self.logging_config_path, max_bytes, backup_count)

            if not success:
                warning_msg = (
                            "Failed to update file rotation settings."
                            "No changes were applied."
                        )
                print(warning_msg)
                return False

            # Log the changes
            if max_bytes is not None:
                LOGGER.info(f"Updated maxBytes: {max_bytes}")

            if backup_count is not None:
                LOGGER.info(f"Updated log retention count: {backup_count}")

            # Try to apply to current session (best-effort)
            try:
                config_data = self.load_logging_config()

                # Create a copy of config for immediate application
                session_config = json.loads(json.dumps(config_data))  # Deep copy

                # Resolve %(logdir)s template if present
                logdir = config_data.get("logdir", "./ilorest_logs")
                resolved_logdir = os.path.abspath(logdir) if not os.path.isabs(logdir) else logdir

                for handler_name, handler_config in session_config.get("handlers", {}).items():
                    if isinstance(handler_config, dict) and "filename" in handler_config:
                        filename = handler_config["filename"]
                        if "%(logdir)s" in filename:
                            handler_config["filename"] = filename.replace("%(logdir)s", resolved_logdir)

                logging.config.dictConfig(session_config)
                LOGGER.info("Applied new file rotation configuration to current session")
            except Exception as ex:
                LOGGER.warning(f"Failed to apply logging config to current session: {str(ex)}")

        except InvalidCommandLineError:
            # Re-raise known command errors
            raise
        except Exception as ex:
            raise InvalidCommandLineError(f"Failed to update file rotation settings in config: {str(ex)}")

    def apply_global_logging_config(self):
        """Apply logging configuration from logging config file to current session

        This method reads the logging configuration and applies the current
        log levels to the session loggers.
        """
        try:
            with open(self.logging_config_path, "r") as config_file:
                config_data = json.load(config_file)

            # Determine the desired runtime level from persistent config and apply via helper
            log_level = config_data.get("loggers", {}).get("", {}).get("level", "INFO")
            runtime_level = logging.DEBUG if log_level == "DEBUG" else logging.INFO
            root_logger = logging.getLogger()

            # Apply runtime logger and handler levels consistently
            try:
                set_runtime_logger_levels(root_logger, runtime_level, set_module_logger=LOGGER)
            except Exception:
                # Fallback in the unlikely event helpers fail
                LOGGER.setLevel(runtime_level)
                root_logger.setLevel(runtime_level)

        except (json.JSONDecodeError, IOError, FileNotFoundError) as ex:
            LOGGER.warning(f"Failed to apply logging config: {str(ex)}")

    def run(self, line, help_disp=False):
        """Main logconfig worker function

        :param line: command line string
        :type line: str.
        """
        if help_disp:
            print("logconfig: Configure persistent logging options.")
            print("Usage: logconfig [--enable-debug | --disable-debug] [--logdir=PATH]")
            print("                 [--log_file_size=SIZE] [--log_retention_count=COUNT] [--show]")
            print("  --enable-debug      Enable debug logging globally for all commands")
            print("  --disable-debug     Disable debug logging globally for all commands")
            print("  --logdir=PATH       Set the directory for log files (use quotes for path)")
            print("  --log_file_size=SIZE Set the maximum size of log files before rotation")
            print("                      Specify in MB format only (e.g., 1MB, 5MB, 10MB)")
            print("  --log_retention_count=COUNT  Set the number of log files to retain")
            print("  --show              Show current logging configuration")
            print("")
            print("Note: Use --enable-debug to enable or --disable-debug to disable persistent debug mode.")
            print("      Without any flags, shows current status.")
            return ReturnCodes.SUCCESS
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)

            # Check for old debug syntax patterns
            line_str = " ".join(line) if isinstance(line, list) else str(line)
            if "--debug" in line_str.lower():
                if len(args) > 0 and args[0].lower() in ["true", "false"]:
                    raise InvalidCommandLineError(
                        f"Invalid argument '{args[0]}'. The --debug true/false syntax is no longer supported. "
                        "Use --enable-debug to enable or --disable-debug to disable debug logging."
                    )
                else:
                    raise InvalidCommandLineError(
                        "The --debug flag is no longer supported. "
                        "Use --enable-debug to enable or --disable-debug to disable debug logging."
                    )

            # Check for unexpected positional arguments that might be from old syntax
            if len(args) > 0 and args[0].lower() in ["true", "false"]:
                raise InvalidCommandLineError(
                    f"Invalid argument '{args[0]}'. "
                    "Use --enable-debug to enable or --disable-debug to disable debug logging."
                )

            # Handle global --logdir flag
            if hasattr(self.rdmc, "opts") and hasattr(self.rdmc.opts, "logdir") and self.rdmc.opts.logdir:
                options.logdir = self.rdmc.opts.logdir
                self.rdmc.opts.logdir = None

            # Handle equals format for logdir: --logdir=path
            if "=" in line_str:
                parts = line_str.split()
                for part in parts:
                    if part.startswith("--logdir="):
                        options.logdir = part.split("=", 1)[1]
                    elif part.startswith("--log_file_size="):
                        try:
                            size_str = part.split("=", 1)[1]
                            options.log_file_size = self.parse_file_size(size_str)
                        except (ValueError, InvalidCommandLineError) as e:
                            raise InvalidCommandLineError(f"log_file_size error: {str(e)}")
                    elif part.startswith("--log_retention_count="):
                        try:
                            options.backup_count = int(part.split("=", 1)[1])
                        except ValueError:
                            raise InvalidCommandLineError("log retention count must be a valid integer")

            # Workaround for logdir: if logdir is None but we have args that look like paths
            if options.logdir is None and len(args) > 0:
                for arg in args:
                    if os.path.isabs(arg) or "/" in arg or "\\" in arg:
                        options.logdir = arg
                        break

        except Exception as ex:
            LOGGER.error(f"Failed to parse command arguments: {str(ex)}")
            return ReturnCodes.GENERAL_ERROR

        logOutput = []

        # Check if show flag was provided - only short-circuit when no action flags are given.
        # If --show is combined with other flags (enable/disable/logdir/etc.)
        # we should process the actions first, then display the configuration
        if hasattr(options, "show") and options.show and not any(
            [
                hasattr(options, "enable_debug") and options.enable_debug,
                hasattr(options, "disable_debug") and options.disable_debug,
                hasattr(options, "logdir") and options.logdir,
                hasattr(options, "log_file_size") and options.log_file_size,
                hasattr(options, "backup_count") and options.backup_count,
            ]
        ):
            try:
                with open(self.logging_config_path, "r") as config_file:
                    config_data = json.load(config_file)

                # Show key logging information
                if "loggers" in config_data and "" in config_data["loggers"]:
                    log_level = config_data["loggers"][""]["level"]
                    debug_enabled = log_level == "DEBUG"

                if "logdir" in config_data:
                    print(f"Log Directory: {config_data['logdir']}")

                # Show file rotation settings for RotatingFileHandler
                rotation_settings = get_config_file_rotation_settings(self.logging_config_path)
                if rotation_settings:
                    for handler_name, settings in rotation_settings.items():
                        max_bytes = settings.get("maxBytes", "Not set")
                        backup_count = settings.get("backupCount", "Not set")
                        print(f"Log File Rotation ({handler_name}):")

                        # Display file size in MB format
                        if max_bytes != "Not set" and isinstance(max_bytes, (int, float)):
                            mb_size = max_bytes / (1024 * 1024)
                            if mb_size == int(mb_size):
                                size_display = f"{int(mb_size)} MB"
                            else:
                                size_display = f"{mb_size:.1f} MB"
                            print(f"  Maximum file size: {size_display}")
                        else:
                            print(f"  Maximum file size: {max_bytes}")

                        print(f"  Log retention count: {backup_count}")

                # Show handlers information
                if "handlers" in config_data:
                    print("Active Levels:")
                    for handler_name, handler_config in config_data["handlers"].items():
                        handler_level = handler_config.get("level", "INFO")
                        print(f"  - {handler_name}: {handler_level}")

            except Exception as ex:
                # ex prints cwd/logging_config.json if configuration file not found
                LOGGER.debug(f"Error reading configuration: {str(ex)}")
                print("JSON configuration file not found")
            return ReturnCodes.SUCCESS

        # Check if enable-debug flag was provided
        if hasattr(options, "enable_debug") and options.enable_debug:
            debug_enabled = True

            # Update current session logging
            LOGGER.setLevel(logging.DEBUG)

            # Also set the root logger to DEBUG to ensure all debug messages are captured
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)

            LOGGER.debug("Debug logging is enabled for current session")

            # Update logging configuration file with new logging levels
            try:
                success = self.update_logging_config_levels(debug_enabled)
                if success:
                    LOGGER.info("Debug logging has been enabled globally.")
                    LOGGER.info("Debug mode will persist for all future iLORest sessions.")
                    LOGGER.info("To disable debug mode, use: logconfig --disable-debug")
                    logOutput.append("Debug logging has been enabled globally.")
                    logOutput.append("Debug mode will persist for all future iLORest sessions.")
                    logOutput.append("To disable debug mode, use: logconfig --disable-debug")
                else:
                    warning_msg = (
                            "Failed to enable debug mode."
                            "No changes were applied."
                        )
                    print(warning_msg)
            except Exception as ex:
                LOGGER.error(f"Failed to update logging config: {str(ex)}")

        # Check if disable-debug flag was provided
        elif hasattr(options, "disable_debug") and options.disable_debug:
            debug_enabled = False

            # Set loggers back to INFO level when debug is disabled
            LOGGER.setLevel(logging.INFO)

            # Reset root logger to INFO
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.INFO)

            LOGGER.info("Debug logging is disabled for current session")

            # Update logging configuration file with new logging levels
            try:
                success = self.update_logging_config_levels(debug_enabled)
                if success:
                    LOGGER.info("Debug logging has been disabled globally.")
                    LOGGER.info("Debug mode is now turned off for all future iLORest sessions.")
                    LOGGER.info("To enable debug mode, use: logconfig --enable-debug")
                    logOutput.append("Debug logging has been disabled globally.")
                    logOutput.append("Debug mode is now turned off for all future iLORest sessions.")
                    logOutput.append("To enable debug mode, use: logconfig --enable-debug")
                else:
                    warning_msg = (
                        "Failed to disable debug mode."
                        "No changes were applied."
                    )
                    print(warning_msg)
            except Exception as ex:
                LOGGER.error(f"Failed to update logging config: {str(ex)}")
                return ReturnCodes.GENERAL_ERROR

        # If no specific action flags were provided and --show was not used, show current status
        if not any(
            [
                hasattr(options, "enable_debug") and options.enable_debug,
                hasattr(options, "disable_debug") and options.disable_debug,
                hasattr(options, "logdir") and options.logdir,
                hasattr(options, "log_file_size") and options.log_file_size,
                hasattr(options, "backup_count") and options.backup_count,
                hasattr(options, "show") and options.show,
            ]
        ):
            try:
                with open(self.logging_config_path, "r") as config_file:
                    config_data = json.load(config_file)

                debug_enabled = False
                if "loggers" in config_data and "" in config_data["loggers"]:
                    log_level = config_data["loggers"][""]["level"]
                    debug_enabled = log_level == "DEBUG"

                if debug_enabled:
                    logOutput.append("Debug logging currently enabled globally.")
                    logOutput.append("To disable persistent debug mode, use: logconfig --disable-debug")
                else:
                    logOutput.append("Debug logging currently disabled globally.")
                    logOutput.append("To enable persistent debug mode, use: logconfig --enable-debug")
            except Exception as ex:
                LOGGER.warning(f"Failed to read logging config: {str(ex)}")
                logOutput.append("Debug logging status unknown.")
                logOutput.append("To enable persistent debug mode, use: logconfig --enable-debug")

        # Configure log directory
        if hasattr(options, "logdir") and options.logdir:
            # For directory creation and writability checks, resolve to absolute path
            resolved_path = os.path.abspath(options.logdir) if not os.path.isabs(options.logdir) else options.logdir

            if not os.path.exists(resolved_path):
                try:
                    os.makedirs(resolved_path, exist_ok=True)
                    LOGGER.info(f"Created log directory: {resolved_path}")
                except OSError as ex:
                    raise InvalidCommandLineError(f"Failed to create log directory '{resolved_path}': {str(ex)}")

            # Verify directory is writable
            if not os.access(resolved_path, os.W_OK):
                raise InvalidCommandLineError(f"Log directory '{resolved_path}' is not writable")

            # Update current session logging configuration
            if hasattr(self.rdmc, "config"):
                self.rdmc.config.logdir = options.logdir

            # Update logging configuration file and apply to handlers
            try:
                self.update_logging_config_logdir(options.logdir)
                logOutput.append(f"Log directory updated to: {options.logdir}")
                logOutput.append("New log files will be written to the specified directory.")
            except Exception as ex:
                LOGGER.error(f"Failed to update log directory configuration: {str(ex)}")
                return ReturnCodes.GENERAL_ERROR

        # Configure log file rotation settings
        if (hasattr(options, "log_file_size") and options.log_file_size is not None) or (
            hasattr(options, "backup_count") and options.backup_count is not None
        ):

            max_bytes = getattr(options, "log_file_size", None)
            backup_count = getattr(options, "backup_count", None)

            # Parse file size if it's a string (from argparse)
            if max_bytes is not None and isinstance(max_bytes, str):
                try:
                    max_bytes = self.parse_file_size(max_bytes)
                except InvalidCommandLineError:
                    raise

            # Validate input values using utility function
            is_valid, error_message = validate_rotation_parameters(max_bytes, backup_count)
            if not is_valid:
                raise InvalidCommandLineError(error_message)

            try:
                success = self.update_logging_config_file_rotation(max_bytes, backup_count)

                if success:
                    if max_bytes is not None:
                        # Display the size in MB format
                        mb_size = max_bytes / (1024 * 1024)
                        if mb_size == int(mb_size):
                            size_display = f"{int(mb_size)} MB"
                        else:
                            size_display = f"{mb_size:.1f} MB"
                        logOutput.append(f"Log file maximum size updated to: {size_display}")

                    if backup_count is not None:
                        logOutput.append(f"Log retention count updated to: {backup_count}")

                    logOutput.append("Log rotation settings have been updated.")
            except Exception as ex:
                LOGGER.error(f"Failed to update log rotation configuration: {str(ex)}")
                return ReturnCodes.GENERAL_ERROR

        # Print summary
        for msg in logOutput:
            print(msg)

        # If the user requested --show along with action flags, display the
        # current configuration now that we've processed the actions.
        if hasattr(options, "show") and options.show:
            try:
                with open(self.logging_config_path, "r") as config_file:
                    config_data = json.load(config_file)

                # Show key logging information
                if "loggers" in config_data and "" in config_data["loggers"]:
                    log_level = config_data["loggers"][""].get("level", "INFO")
                    debug_enabled = log_level == "DEBUG"

                if "logdir" in config_data:
                    print(f"Log Directory: {config_data['logdir']}")

                # Show file rotation settings for RotatingFileHandler
                rotation_settings = get_config_file_rotation_settings(self.logging_config_path)
                if rotation_settings:
                    for handler_name, settings in rotation_settings.items():
                        max_bytes = settings.get("maxBytes", "Not set")
                        backup_count = settings.get("backupCount", "Not set")
                        print(f"Log File Rotation ({handler_name}):")

                        if max_bytes != "Not set" and isinstance(max_bytes, (int, float)):
                            mb_size = max_bytes / (1024 * 1024)
                            if mb_size == int(mb_size):
                                size_display = f"{int(mb_size)} MB"
                            else:
                                size_display = f"{mb_size:.1f} MB"
                            print(f"  Maximum file size: {size_display}")
                        else:
                            print(f"  Maximum file size: {max_bytes}")

                        print(f"  Log retention count: {backup_count}")

                # Show handlers information
                if "handlers" in config_data:
                    print("Active Levels:")
                    for handler_name, handler_config in config_data["handlers"].items():
                        handler_level = handler_config.get("level", "INFO")
                        print(f"  - {handler_name}: {handler_level}")

            except Exception as ex:
                LOGGER.debug(f"Error reading configuration for --show after actions: {str(ex)}")
                print("JSON configuration file not found")
        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """arguments for the logconfig command"""
        if not customparser:
            return

        # Debug control arguments
        customparser.add_argument(
            "--enable-debug",
            dest="enable_debug",
            action="store_true",
            help=(
                "Enable persistent debug logging for all commands. "
                "If not provided, debug logging state remains unchanged."
            ),
        )

        customparser.add_argument(
            "--disable-debug",
            dest="disable_debug",
            action="store_true",
            help=("Disable persistent debug logging for all commands."),
        )

        # Log directory argument
        customparser.add_argument(
            "--logdir",
            dest="logdir",
            help="Set the directory for log files and update logging configuration.",
            metavar="PATH",
        )

        # Log file rotation argument
        customparser.add_argument(
            "--log_file_size",
            dest="log_file_size",
            type=str,
            help="Set the maximum size of log files before rotation. "
            "Specify in MB format only (e.g., 1MB, 5MB, 10MB).",
            metavar="SIZE",
        )

        # Log retention count argument
        customparser.add_argument(
            "--log_retention_count",
            dest="backup_count",
            type=int,
            help="Set the number of log files to retain during rotation.",
            metavar="COUNT",
        )

        # Show current configuration
        customparser.add_argument(
            "--show",
            dest="show",
            action="store_true",
            help="Show current logging configuration.",
            default=False,
        )
