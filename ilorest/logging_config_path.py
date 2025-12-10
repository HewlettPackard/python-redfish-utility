"""Helper to determine logging_config.json path for different platforms.

"""

import os


def get_logging_config_path():
    r"""Return path for logging_config.json.

    Iterates through a list of different platform paths and returns the first one where
    the directory exists and logging_config.json is present.
    Platform paths: C:\Program Files\Hewlett Packard Enterprise\RESTful Interface Tool,
    /opt/ilorest, /etc/ilorest, C:\Python313\Lib\site-packages\ilorest.
    Falls back to the current working directory if none are found.
    """
    platform_paths = [
        r"C:\Program Files\Hewlett Packard Enterprise\RESTful Interface Tool",
        "/opt/ilorest",
        "/etc/ilorest",
        r"C:\Python313\Lib\site-packages\ilorest",
    ]
    for path in platform_paths:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "logging_config.json")):
            return os.path.join(path, "logging_config.json")
    # Fallback to current working directory
    return os.path.join(os.getcwd(), "logging_config.json")
