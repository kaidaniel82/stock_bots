"""Theme configuration for Trailing Stop Manager.

Bloomberg Terminal Style - Dark with orange/amber accents.
"""

# =============================================================================
# COLOR PALETTE - Bloomberg Terminal Style
# =============================================================================

COLORS = {
    # Primary - Bloomberg Orange/Amber
    "primary": "#FF9500",  # Bloomberg Orange
    "primary_dark": "#E08600",
    "primary_muted": "rgba(255, 149, 0, 0.15)",
    "accent": "#FF9500",

    # Backgrounds - True black/dark
    "bg_app": "#000000",  # Pure black
    "bg_surface": "#0D0D0D",  # Slightly lighter
    "bg_elevated": "#1A1A1A",
    "bg_hover": "#262626",
    "bg_panel": "#0A0A0A",  # Panel background

    # Text
    "text_primary": "#FFFFFF",
    "text_secondary": "#B0B0B0",
    "text_muted": "#707070",
    "text_inverse": "#000000",
    "text_amber": "#FFB347",  # Bloomberg amber text

    # Borders - Visible grid lines
    "border": "#333333",
    "border_light": "#404040",
    "border_accent": "#FF9500",  # Orange border accent

    # Status colors - Bloomberg style
    "success": "#00D26A",  # Bright green
    "warning": "#FFB347",  # Amber
    "error": "#FF3B30",    # Red
    "info": "#00BFFF",     # Cyan/blue

    # Trading specific
    "profit": "#00D26A",   # Green
    "loss": "#FF3B30",     # Red
    "hwm": "#00BFFF",      # High water mark - cyan
    "stop": "#FF3B30",     # Stop price - red
    "limit": "#FFA500",    # Limit price - orange
    "bid": "#FFB347",      # Bid - amber
    "connected": "#00D26A",
    "disconnected": "#FF3B30",

    # Market status backgrounds (for legs display)
    "market_open_bg": "rgba(0, 210, 106, 0.15)",    # Greenish when market open
    "market_closed_bg": "rgba(112, 112, 112, 0.15)",  # Gray when market closed
}


# =============================================================================
# TYPOGRAPHY - Monospace for terminal feel
# =============================================================================

TYPOGRAPHY = {
    "font_family": "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Consolas', monospace",
    "font_family_display": "'Inter', -apple-system, sans-serif",  # For headings
    "font_normal": "400",
    "font_medium": "500",
    "font_semibold": "600",
    "font_bold": "700",
    "font_size_xs": "0.7rem",
    "font_size_sm": "0.8rem",
    "font_size_md": "0.9rem",
    "font_size_lg": "1rem",
}


# =============================================================================
# TAB STYLES - Bloomberg style tabs
# =============================================================================

TAB_STYLES = {
    "container_border_bottom": f"1px solid {COLORS['border']}",
    "container_background": COLORS["bg_surface"],
    "tab_padding": "0.75rem 1.25rem",
    "tab_color": COLORS["text_secondary"],
    "tab_hover_color": COLORS["primary"],
    "tab_active_color": COLORS["primary"],
    "tab_active_border_bottom": f"2px solid {COLORS['primary']}",
    "tab_inactive_border_bottom": "2px solid transparent",
    "tab_active_font_weight": TYPOGRAPHY["font_semibold"],
    "tab_inactive_font_weight": TYPOGRAPHY["font_medium"],
    "tab_transition": "all 0.15s ease",
    "tab_font_size": TYPOGRAPHY["font_size_sm"],
}


# =============================================================================
# CARD/PANEL STYLES - Bloomberg grid panels
# =============================================================================

CARD_STYLES = {
    "background": COLORS["bg_surface"],
    "border": f"1px solid {COLORS['border']}",
    "border_radius": "2px",  # Sharp corners for terminal look
    "padding": "0.75rem",
    "hover_border": f"1px solid {COLORS['border_light']}",
}

PANEL_STYLES = {
    "background": COLORS["bg_panel"],
    "border": f"1px solid {COLORS['border']}",
    "border_left": f"3px solid {COLORS['primary']}",  # Orange accent left border
    "border_radius": "0",  # No rounded corners
    "padding": "1rem",
    "margin": "0.5rem",
    "header_color": COLORS["primary"],
    "header_size": TYPOGRAPHY["font_size_sm"],
}


# =============================================================================
# BUTTON STYLES
# =============================================================================

BUTTON_STYLES = {
    "primary": {
        "background": COLORS["primary"],
        "color": COLORS["text_inverse"],
        "font_weight": TYPOGRAPHY["font_semibold"],
        "border_radius": "2px",
        "_hover": {"background": COLORS["primary_dark"]},
    },
    "danger": {
        "background": COLORS["error"],
        "color": COLORS["text_primary"],
        "border_radius": "2px",
        "_hover": {"opacity": "0.9"},
    },
    "secondary": {
        "background": "transparent",
        "color": COLORS["primary"],
        "border": f"1px solid {COLORS['primary']}",
        "border_radius": "2px",
        "_hover": {"background": COLORS["primary_muted"]},
    },
}


# =============================================================================
# LAYOUT DIMENSIONS
# =============================================================================

LAYOUT = {
    # Topbar
    "topbar_height": "48px",  # Compact header

    # Content Area
    "content_max_width": "100%",  # Full width for terminal
    "content_padding": "0.5rem 1rem 0.5rem 1rem",  # top right bottom left

    # Sidebar panels
    "sidebar_width": "300px",
    "panel_gap": "1px",  # Thin gaps between panels
}


# =============================================================================
# TOPBAR STYLES - Bloomberg header bar
# =============================================================================

TOPBAR_STYLES = {
    "height": LAYOUT["topbar_height"],
    "background": COLORS["bg_surface"],
    "border_bottom": f"1px solid {COLORS['border']}",
    "padding": "0 1rem",

    # Logo
    "logo_font_size": "1rem",
    "logo_font_weight": TYPOGRAPHY["font_bold"],
    "logo_color": COLORS["primary"],
}


# =============================================================================
# DATA TABLE STYLES - Bloomberg data grid
# =============================================================================

TABLE_STYLES = {
    "header_background": COLORS["bg_elevated"],
    "header_color": COLORS["primary"],
    "header_font_size": TYPOGRAPHY["font_size_xs"],
    "header_font_weight": TYPOGRAPHY["font_semibold"],
    "row_background": COLORS["bg_surface"],
    "row_alt_background": COLORS["bg_panel"],
    "row_hover": COLORS["bg_hover"],
    "cell_padding": "0.5rem 0.75rem",
    "border": f"1px solid {COLORS['border']}",
}


# =============================================================================
# STATUS INDICATORS
# =============================================================================

STATUS_STYLES = {
    "dot_size": "8px",
    "connected_color": COLORS["connected"],
    "disconnected_color": COLORS["disconnected"],
    "pulse_animation": "pulse 2s infinite",
}


# =============================================================================
# HEADER STYLES (backwards compatibility)
# =============================================================================

HEADER_STYLES = {
    "background": COLORS["bg_surface"],
    "border_bottom": f"1px solid {COLORS['border']}",
    "padding": "0 1rem",
}
