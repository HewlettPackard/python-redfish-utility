###
# Copyright 2021-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
###
# -*- coding: utf-8 -*-
"""Progress tracking module for ComputeOpsManagement bulk operations"""


class ProgressTracker:
    """Handles progress bar display for bulk operations"""

    def __init__(self, total: int, desc: str = "", unit: str = ""):
        """Initialize progress tracker

        :param total: Total number of items
        :param desc: Description for progress bar
        :param unit: Unit of measurement
        """
        self.total = total
        self.desc = desc
        self.unit = unit
        self.current = 0
        self.status_info = ""

        # Display initial progress
        self._display()

    def update(self, n: int = 1, status: str = ""):
        """Update progress by n items

        :param n: Number of items completed
        :param status: Optional status message
        """
        self.current += n
        self.status_info = f" - {status}" if status else ""
        self._display()

    def set_description(self, desc: str):
        """Update description

        :param desc: New description
        """
        self.desc = desc
        self._display()

    def close(self):
        """Close progress bar with newline"""
        print()  # Move to next line

    def _display(self):
        """Display progress bar"""
        progress_bar = self._get_progress_bar()
        print(f"\r{self.desc}: {self.current}/{self.total} " f"{progress_bar}{self.status_info}", end="", flush=True)

    def _get_progress_bar(self, width: int = 40) -> str:
        """Generate visual progress bar

        :param width: Width of progress bar
        :returns: Progress bar string
        """
        progress_pct = (self.current / self.total * 100) if self.total > 0 else 0
        filled_length = int(width * self.current // self.total) if self.total > 0 else 0
        bar = "#" * filled_length + "-" * (width - filled_length)
        return f"[{bar}] {progress_pct:.1f}%"


class TqdmProgressTracker:
    """Wrapper for tqdm progress bar when available"""

    def __init__(self, tqdm_instance):
        """Initialize with tqdm instance

        :param tqdm_instance: tqdm progress bar object
        """
        self.pbar = tqdm_instance

    def update(self, n: int = 1, status: str = ""):
        """Update progress

        :param n: Number of items completed
        :param status: Optional status message
        """
        if status:
            self.pbar.set_postfix_str(status)
        self.pbar.update(n)

    def set_description(self, desc: str):
        """Update description

        :param desc: New description
        """
        self.pbar.set_description(desc)

    def close(self):
        """Close progress bar"""
        self.pbar.close()


def create_progress_tracker(total: int, desc: str = "", unit: str = ""):
    """Factory function to create appropriate progress tracker

    :param total: Total number of items
    :param desc: Description
    :param unit: Unit of measurement
    :returns: Progress tracker instance
    """
    try:
        from tqdm import tqdm

        pbar = tqdm(total=total, desc=desc, unit=unit)
        return TqdmProgressTracker(pbar)
    except ImportError:
        return ProgressTracker(total, desc, unit)
