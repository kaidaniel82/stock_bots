"""Trailing Stop Manager - Main App.

RiskRanger-style Layout: Sticky Topbar + Content Area
"""
import reflex as rx

from .state import AppState
from .components import (
    topbar, tab_navigation,
    setup_tab, monitor_tab,
    delete_confirmation_dialog,
)
from .ui_config.theme import COLORS, LAYOUT


def app_layout() -> rx.Component:
    """
    App Layout: Sticky Topbar + Tab Navigation + Content

    Layout structure (RiskRanger style):
    - Topbar: sticky, 64px height
    - Tab Navigation: sticky below topbar
    - Content: scrollable, with padding
    """
    return rx.box(
        # Interval for real-time updates (every 500ms)
        # MUST run always - also during disconnect to detect reconnect status
        rx.moment(interval=500, on_change=AppState.tick_update),

        # Sticky Topbar
        topbar(),

        # Tab Navigation
        tab_navigation(),

        # Content Area
        rx.box(
            rx.cond(
                AppState.active_tab == "setup",
                setup_tab(),
                monitor_tab(),
            ),
            padding=LAYOUT["content_padding"],
            max_width=LAYOUT["content_max_width"],
            margin="0 auto",  # Center content
            overflow_y="auto",
            min_height="calc(100vh - 64px)",
        ),

        # Delete confirmation dialog
        delete_confirmation_dialog(),

        background=COLORS["bg_app"],
        min_height="100vh",
    )


def index() -> rx.Component:
    """Main page entry point."""
    return app_layout()


app = rx.App(
    theme=rx.theme(
        appearance="dark",
        accent_color="green",
    ),
)
app.add_page(index, on_load=AppState.on_mount)
