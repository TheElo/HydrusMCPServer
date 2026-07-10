"""Hydrus MCP Tools - Modular tool implementations."""

# Tab tools
from .tab_tools import (
    hydrus_get_page_info,
    hydrus_list_tabs,
    hydrus_focus_on_tab,
    hydrus_send_to_tab,
)

# Sense tools (vision/audio)
from .sense_tools import (
    hydrus_show_files,
    hydrus_inspect_files,
    hydrus_transcribe_audio,
)

__all__ = [
    "hydrus_get_page_info",
    "hydrus_list_tabs",
    "hydrus_focus_on_tab",
    "hydrus_send_to_tab",
    "hydrus_show_files",
    "hydrus_inspect_files",
    "hydrus_transcribe_audio",
]
