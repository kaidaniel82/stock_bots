"""UI Components for Trailing Stop Manager."""
import reflex as rx

from .state import AppState
from .ui_config.theme import (
    COLORS, TAB_STYLES, CARD_STYLES, TOPBAR_STYLES, LAYOUT,
    PANEL_STYLES, TYPOGRAPHY, TABLE_STYLES
)


# =============================================================================
# TAB BUTTON COMPONENT (RiskRanger style)
# =============================================================================

def tab_button(tab_id: str, tab_name: str) -> rx.Component:
    """Tab button with underline indicator (RiskRanger style)."""
    return rx.text(
        tab_name,
        padding=TAB_STYLES["tab_padding"],
        color=rx.cond(
            AppState.active_tab == tab_id,
            COLORS["primary"],
            COLORS["text_secondary"],
        ),
        font_weight=rx.cond(
            AppState.active_tab == tab_id,
            TAB_STYLES["tab_active_font_weight"],
            TAB_STYLES["tab_inactive_font_weight"],
        ),
        cursor="pointer",
        border_bottom=rx.cond(
            AppState.active_tab == tab_id,
            TAB_STYLES["tab_active_border_bottom"],
            TAB_STYLES["tab_inactive_border_bottom"],
        ),
        _hover={"color": COLORS["text_primary"]},
        transition=TAB_STYLES["tab_transition"],
        on_click=lambda: AppState.set_active_tab(tab_id),
    )


# =============================================================================
# HEADER COMPONENTS
# =============================================================================

def topbar() -> rx.Component:
    """
    Sticky Topbar - Logo + Connection + Controls (RiskRanger style)
    """
    return rx.box(
        rx.hstack(
            # Logo (links)
            rx.hstack(
                rx.icon(
                    "trending-up",
                    size=24,
                    color=COLORS["accent"],
                ),
                rx.text(
                    "Trailing Stop",
                    font_size=TOPBAR_STYLES["logo_font_size"],
                    font_weight=TOPBAR_STYLES["logo_font_weight"],
                    color=COLORS["accent"],
                ),
                spacing="2",
                align_items="center",
            ),

            rx.spacer(),

            # Connection status with reconnect support
            rx.hstack(
                # Status badge with 3 colors: green=connected, yellow=reconnecting, red=disconnected
                rx.badge(
                    AppState.connection_status,
                    color_scheme=rx.cond(
                        AppState.is_connected,
                        "green",
                        rx.cond(
                            AppState.connection_status.contains("onnect"),  # Connecting/Reconnecting
                            "yellow",
                            "red",
                        ),
                    ),
                ),
                # Connect/Disconnect buttons
                rx.cond(
                    AppState.is_connected,
                    rx.button(
                        "Disconnect",
                        on_click=AppState.disconnect_tws,
                        color_scheme="red",
                        size="1",
                    ),
                    rx.button(
                        "Connect",
                        on_click=AppState.connect_tws,
                        color_scheme="green",
                        size="1",
                        disabled=AppState.connection_status != "Disconnected",
                    ),
                ),
                spacing="2",
            ),
            # Cancel All Orders button
            rx.button(
                "Cancel All Orders",
                on_click=AppState.cancel_all_orders,
                color_scheme="orange",
                size="1",
                disabled=~AppState.is_connected,
            ),

            width="100%",
            align_items="center",
            height="100%",
        ),
        height=TOPBAR_STYLES["height"],
        padding=TOPBAR_STYLES["padding"],
        background=COLORS["bg_surface"],
        border_bottom=TOPBAR_STYLES["border_bottom"],
        position="sticky",
        top="0",
        z_index="1000",
        display="flex",
        align_items="center",
    )


def header_panel() -> rx.Component:
    """Legacy alias for topbar."""
    return topbar()


def tab_navigation() -> rx.Component:
    """Tab navigation between Setup and Monitor (RiskRanger style)."""
    return rx.hstack(
        rx.hstack(
            tab_button("setup", "Setup"),
            tab_button("monitor", "Monitor"),
            spacing="0",
        ),
        rx.spacer(),
        rx.text(AppState.status_message, size="2", color=COLORS["text_muted"]),
        width="100%",
        padding_x="4",
        padding_y="0",
        align="center",
        background=COLORS["bg_app"],
        border_bottom=TAB_STYLES["container_border_bottom"],
        position="sticky",
        top="48px",  # Below topbar (height ~48px)
        z_index="999",
    )


# =============================================================================
# SETUP TAB COMPONENTS
# =============================================================================

def position_row(row: list) -> rx.Component:
    """Single position row from computed var."""
    con_id = row[0].to(int)
    con_id_str = row[0]
    pnl_color = row[16]           # shifted by 1
    is_selected = row[17] == "true"
    qty_usage = row[18]           # e.g., "2/3"
    is_fully_used = row[19] == "true"
    selected_qty = row[20]        # Selected qty for this group
    market_status = row[23]       # "Open", "Closed", or "Unknown"

    # Row styling based on fully_used status
    row_opacity = rx.cond(is_fully_used, "0.5", "1.0")
    row_bg = rx.cond(is_fully_used, COLORS["bg_elevated"], "transparent")

    return rx.table.row(
        rx.table.cell(
            rx.checkbox(
                checked=is_selected,
                on_change=AppState.toggle_position(con_id),
                disabled=is_fully_used,
            )
        ),
        rx.table.cell(row[1]),   # symbol
        rx.table.cell(rx.badge(row[2], color_scheme="gray")),  # type_str
        rx.table.cell(row[3]),   # expiry
        rx.table.cell(row[4]),   # strike_str
        rx.table.cell(row[5]),   # side_str (C/P)
        rx.table.cell(row[6]),   # quantity_str
        rx.table.cell(
            rx.text(
                qty_usage,
                color=rx.cond(is_fully_used, COLORS["error"], COLORS["success"]),
                font_weight=rx.cond(is_fully_used, "bold", "normal"),
            )
        ),  # usage (e.g., "2/3")
        # Selected Qty dropdown - only visible when checkbox is selected
        rx.table.cell(
            rx.cond(
                is_fully_used,
                rx.text("-", color=COLORS["text_muted"]),
                rx.cond(
                    is_selected,
                    rx.select(
                        row[22].split(","),  # qty_options as comma-separated string -> list
                        value=selected_qty,
                        on_change=AppState.set_position_quantity(con_id_str),
                        size="1",
                    ),
                    rx.text("-", color=COLORS["text_muted"]),  # Hidden when not selected
                ),
            )
        ),
        rx.table.cell(row[7]),   # fill_price
        rx.table.cell(row[8]),   # bid
        rx.table.cell(row[9]),   # mid
        rx.table.cell(row[10]),  # ask
        rx.table.cell(row[11]),  # last
        rx.table.cell(row[12]),  # mark
        rx.table.cell(rx.text(row[15], color=pnl_color)),  # pnl with color
        rx.table.cell(
            rx.badge(
                market_status,
                color_scheme=rx.cond(
                    market_status == "Open",
                    "green",
                    rx.cond(market_status == "Closed", "red", "gray"),
                ),
                size="1",
            )
        ),  # market status
        style={"opacity": row_opacity, "background": row_bg},
    )


def portfolio_table() -> rx.Component:
    """Portfolio positions table - Bloomberg terminal style."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("PORTFOLIO", size="2", weight="bold", color=COLORS["primary"],
                       font_family=TYPOGRAPHY["font_family"]),
                rx.spacer(),
                rx.text(f"#{AppState.refresh_tick}", size="1", color=COLORS["text_muted"],
                       font_family=TYPOGRAPHY["font_family"]),
                width="100%",
            ),
            rx.cond(
                AppState.is_connected,
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell(""),
                            rx.table.column_header_cell("SYMBOL"),
                            rx.table.column_header_cell("TYPE"),
                            rx.table.column_header_cell("EXPIRY"),
                            rx.table.column_header_cell("STRIKE"),
                            rx.table.column_header_cell("SIDE"),
                            rx.table.column_header_cell("QTY"),
                            rx.table.column_header_cell("USAGE"),
                            rx.table.column_header_cell("SEL"),
                            rx.table.column_header_cell("FILL"),
                            rx.table.column_header_cell("BID"),
                            rx.table.column_header_cell("MID"),
                            rx.table.column_header_cell("ASK"),
                            rx.table.column_header_cell("LAST"),
                            rx.table.column_header_cell("MARK"),
                            rx.table.column_header_cell("P&L"),
                            rx.table.column_header_cell("MKT"),
                        )
                    ),
                    rx.table.body(
                        rx.foreach(AppState.position_rows, position_row)
                    ),
                    width="100%",
                    size="1",
                ),
                rx.text("Connect to TWS to see positions", color=COLORS["text_muted"],
                       font_family=TYPOGRAPHY["font_family"]),
            ),
            width="100%",
            spacing="2",
        ),
        background=COLORS["bg_panel"],
        border=PANEL_STYLES["border"],
        border_left=PANEL_STYLES["border_left"],
        border_radius=PANEL_STYLES["border_radius"],
        padding=PANEL_STYLES["padding"],
        width="100%",
    )


def create_group_panel() -> rx.Component:
    """Panel to create new group from selection - Bloomberg style."""
    return rx.box(
        rx.hstack(
            rx.text("NEW GROUP", size="2", weight="bold", color=COLORS["primary"],
                   font_family=TYPOGRAPHY["font_family"]),
            rx.input(
                placeholder="Group name",
                value=AppState.new_group_name,
                on_change=AppState.set_new_group_name,
                width="200px",
                size="2",
            ),
            rx.button(
                "Create Group",
                on_click=AppState.create_group,
                background=COLORS["primary"],
                color=COLORS["text_inverse"],
                size="2",
                disabled=~AppState.is_connected,
                _hover={"background": COLORS["primary_dark"]},
            ),
            rx.text(
                f"Selected: {AppState.selected_quantities.length()} positions",
                size="2",
                color=COLORS["text_muted"],
                font_family=TYPOGRAPHY["font_family"],
            ),
            spacing="3",
            align="center",
        ),
        background=COLORS["bg_panel"],
        border=PANEL_STYLES["border"],
        border_left=PANEL_STYLES["border_left"],
        border_radius=PANEL_STYLES["border_radius"],
        padding=PANEL_STYLES["padding"],
        width="100%",
    )


# =============================================================================
# SHARED GROUP CARD COMPONENTS
# =============================================================================

def _group_header(group: dict, is_selected: bool = False) -> rx.Component:
    """Group card header with name, badges, and status."""
    is_active = group["is_active"]
    return rx.hstack(
        rx.text(group["name"], size="2", weight="bold", color=COLORS["primary"],
               font_family=TYPOGRAPHY["font_family"]),
        rx.badge(group["total_qty_str"], color_scheme="blue", size="1"),
        rx.badge(
            group["market_status"],
            color_scheme=rx.cond(
                group["market_status"] == "Open",
                "green",
                rx.cond(group["market_status"] == "Closed", "red", "gray"),
            ),
            size="1",
        ),
        rx.badge(
            rx.cond(is_active, "ACTIVE", "IDLE"),
            color_scheme=rx.cond(is_active, "green", "gray"),
            size="1",
        ),
        rx.cond(
            is_selected,
            rx.badge("SELECTED", color_scheme="purple", size="1"),
            rx.fragment(),
        ),
        width="100%",
    )


def _group_prices_row(group: dict, size: str = "2") -> rx.Component:
    """Price row with trigger-type highlighting."""
    return rx.hstack(
        rx.vstack(
            rx.text("Mid", size="1", color=rx.cond(
                group["trigger_price_type"] == "mid", COLORS["accent"], COLORS["text_muted"])),
            rx.text(group["mid_value_str"], size=size, weight="bold", color=rx.cond(
                group["trigger_price_type"] == "mid", COLORS["accent"], COLORS["text_primary"])),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Mark", size="1", color=rx.cond(
                group["trigger_price_type"] == "mark", COLORS["accent"], COLORS["text_muted"])),
            rx.text(group["mark_value_str"], size=size, weight="bold", color=rx.cond(
                group["trigger_price_type"] == "mark", COLORS["accent"], COLORS["text_primary"])),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Bid", size="1", color=rx.cond(
                group["trigger_price_type"] == "bid", COLORS["accent"], COLORS["text_muted"])),
            rx.text(group["spread_bid_str"], size=size, weight="bold", color=rx.cond(
                group["trigger_price_type"] == "bid", COLORS["accent"], COLORS["text_primary"])),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Ask", size="1", color=rx.cond(
                group["trigger_price_type"] == "ask", COLORS["accent"], COLORS["text_muted"])),
            rx.text(group["spread_ask_str"], size=size, weight="bold", color=rx.cond(
                group["trigger_price_type"] == "ask", COLORS["accent"], COLORS["text_primary"])),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("P&L", size="1", color=COLORS["text_muted"]),
            rx.text(group["pnl_mark_str"], size=size, weight="bold", color=group["pnl_color"]),
            align="center", spacing="0",
        ),
        spacing="3",
        width="100%",
    )


def _group_greeks_row(group: dict) -> rx.Component:
    """Greeks row (Delta, Gamma, Theta, Vega)."""
    return rx.hstack(
        rx.vstack(
            rx.text("Delta", size="1", color=COLORS["text_muted"]),
            rx.text(group["delta_str"], size="1", color=COLORS["text_secondary"]),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Gamma", size="1", color=COLORS["text_muted"]),
            rx.text(group["gamma_str"], size="1", color=COLORS["text_secondary"]),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Theta", size="1", color=COLORS["text_muted"]),
            rx.text(group["theta_str"], size="1", color=COLORS["text_secondary"]),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Vega", size="1", color=COLORS["text_muted"]),
            rx.text(group["vega_str"], size="1", color=COLORS["text_secondary"]),
            align="center", spacing="0",
        ),
        spacing="3",
        width="100%",
    )


def _group_hwm_stop_row(group: dict, show_trail: bool = False) -> rx.Component:
    """HWM, Stop, Fill/Cost, and optionally Trail display."""
    items = [
        rx.vstack(
            rx.text("Fill", size="1", color=COLORS["text_muted"]),
            rx.text(group["cost_str"], size="1", color=COLORS["text_secondary"]),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("HWM", size="1", color=COLORS["text_muted"]),
            rx.text(group["hwm_str"], size="1", color=COLORS["hwm"]),
            align="center", spacing="0",
        ),
        rx.vstack(
            rx.text("Stop", size="1", color=COLORS["text_muted"]),
            rx.text(group["stop_str"], size="1", color=COLORS["stop"]),
            align="center", spacing="0",
        ),
    ]
    if show_trail:
        items.append(
            rx.vstack(
                rx.text("Trail", size="1", color=COLORS["text_muted"]),
                rx.text(group["trail_display"], size="1", color=COLORS["text_secondary"]),
                align="center", spacing="0",
            )
        )
    return rx.hstack(*items, spacing="3", width="100%")


def _group_action_buttons(group_id: str, is_active: bool) -> rx.Component:
    """Action buttons (Activate/Deactivate, Cancel, Delete)."""
    return rx.hstack(
        rx.button(
            rx.cond(is_active, "Deactivate", "Activate"),
            on_click=AppState.toggle_group_active(group_id),
            color_scheme=rx.cond(is_active, "orange", "blue"),
            size="1",
        ),
        rx.button(
            "Cancel",
            on_click=AppState.cancel_group_order(group_id),
            color_scheme="yellow",
            size="1",
        ),
        rx.button(
            "Delete",
            on_click=AppState.request_delete_group(group_id),
            color_scheme="red",
            size="1",
        ),
        spacing="1",
        width="100%",
    )


def _group_trailing_config(group: dict, group_id: str) -> rx.Component:
    """Trailing stop configuration section (Setup mode only)."""
    return rx.vstack(
        rx.divider(color=COLORS["border"]),
        rx.text("Trailing Stop", size="1", weight="bold", color=COLORS["text_muted"]),
        rx.hstack(
            rx.vstack(
                rx.text("Mode", size="1", color=COLORS["text_muted"]),
                rx.select(
                    ["percent", "absolute"],
                    value=group["trail_mode"],
                    on_change=AppState.update_group_trail_mode(group_id),
                    size="1",
                ),
                align="center", spacing="0",
            ),
            rx.vstack(
                rx.text("Trail", size="1", color=COLORS["text_muted"]),
                rx.input(
                    value=group["trail_value"].to(str),
                    on_change=AppState.update_group_trail(group_id),
                    width="50px",
                    size="1",
                ),
                align="center", spacing="0",
            ),
            rx.vstack(
                rx.text("Trigger", size="1", color=COLORS["text_muted"]),
                rx.select(
                    ["mark", "mid", "bid", "ask", "last"],
                    value=group["trigger_price_type"],
                    on_change=AppState.update_group_trigger_price_type(group_id),
                    size="1",
                ),
                align="center", spacing="0",
            ),
            rx.vstack(
                rx.text("Type", size="1", color=COLORS["text_muted"]),
                rx.select(
                    ["market", "limit"],
                    value=group["stop_type"],
                    on_change=AppState.update_group_stop_type(group_id),
                    size="1",
                ),
                align="center", spacing="0",
            ),
            rx.cond(
                group["stop_type"] == "limit",
                rx.vstack(
                    rx.text("Offset", size="1", color=COLORS["text_muted"]),
                    rx.input(
                        value=group["limit_offset"].to(str),
                        on_change=AppState.update_group_limit_offset(group_id),
                        width="50px",
                        size="1",
                    ),
                    align="center", spacing="0",
                ),
                rx.box(),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
        spacing="2",
    )


def _group_time_exit_config(group: dict, group_id: str) -> rx.Component:
    """Time exit configuration section (Setup mode only)."""
    return rx.vstack(
        rx.divider(color=COLORS["border"]),
        rx.hstack(
            rx.checkbox(
                checked=group["time_exit_enabled"],
                on_change=AppState.update_group_time_exit_enabled(group_id),
                size="1",
            ),
            rx.text("Time Exit", size="1", color=COLORS["text_secondary"]),
            rx.cond(
                group["time_exit_enabled"],
                rx.hstack(
                    rx.text("at", size="1", color=COLORS["text_muted"]),
                    rx.input(
                        value=group["time_exit_time"],
                        on_change=AppState.update_group_time_exit_time(group_id),
                        width="60px",
                        size="1",
                    ),
                    rx.text("ET", size="1", color=COLORS["text_muted"]),
                    spacing="1",
                    align="center",
                ),
                rx.box(),
            ),
            spacing="2",
            align="center",
        ),
        width="100%",
    )


def group_card(group: dict, mode: str = "setup") -> rx.Component:
    """Unified group card component.

    Args:
        group: Group data dict
        mode: "setup" (full config) or "monitor" (compact, clickable)
    """
    group_id = group["id"]
    is_active = group["is_active"]
    is_selected = AppState.selected_group_id == group_id

    # Common content for both modes
    content = [
        _group_header(group, is_selected if mode == "monitor" else False),
    ]

    # Legs (Setup mode only)
    if mode == "setup":
        content.append(
            rx.box(
                rx.text(group["legs_str"], size="1", white_space="pre-wrap", color=COLORS["text_secondary"]),
                padding="2",
                background=COLORS["bg_elevated"],
                border_radius="6px",
                width="100%",
            )
        )

    # Prices row
    content.append(_group_prices_row(group, size="2" if mode == "setup" else "1"))

    # Greeks row
    content.append(_group_greeks_row(group))

    # Trailing config (Setup mode only)
    if mode == "setup":
        content.append(_group_trailing_config(group, group_id))

    # HWM/Stop row
    content.append(_group_hwm_stop_row(group, show_trail=(mode == "monitor")))

    # Time exit config (Setup mode only)
    if mode == "setup":
        content.append(_group_time_exit_config(group, group_id))

    # Action buttons
    content.append(_group_action_buttons(group_id, is_active))

    # Build card with mode-specific styling
    card_props = {
        "background": COLORS["bg_panel"],
        "border": PANEL_STYLES["border"],
        "border_radius": PANEL_STYLES["border_radius"],
        "padding": PANEL_STYLES["padding"],
        "width": "100%",
    }

    if mode == "monitor":
        card_props["on_click"] = AppState.select_group(group_id)
        card_props["cursor"] = "pointer"
        card_props["border_left"] = rx.cond(
            is_selected,
            f"3px solid {COLORS['accent']}",
            PANEL_STYLES["border_left"],
        )
        card_props["_hover"] = {"background": COLORS["bg_elevated"]}
    else:
        card_props["border_left"] = PANEL_STYLES["border_left"]

    return rx.box(
        rx.vstack(*content, width="100%", spacing="2"),
        **card_props,
    )


# Wrapper functions for backward compatibility
def group_config_card(group: dict) -> rx.Component:
    """Setup tab group card (full config)."""
    return group_card(group, mode="setup")


def compact_group_card(group: dict) -> rx.Component:
    """Monitor tab group card (compact, clickable)."""
    return group_card(group, mode="monitor")


def setup_tab() -> rx.Component:
    """Setup tab content - Portfolio and Group configuration."""
    return rx.vstack(
        # Portfolio section
        portfolio_table(),
        create_group_panel(),
        # Groups section
        rx.heading("Groups", size="4", color=COLORS["text_primary"]),
        rx.cond(
            AppState.groups.length() > 0,
            rx.grid(
                rx.foreach(AppState.groups, group_config_card),
                columns="3",
                spacing="3",
                width="100%",
            ),
            rx.text("No groups yet. Select positions and create a group.", color=COLORS["text_muted"]),
        ),
        width="100%",
        spacing="4",
    )


# =============================================================================
# MONITOR TAB COMPONENTS
# =============================================================================

def underlying_chart() -> rx.Component:
    """Chart A: Underlying price history (3D, 3min candlesticks)."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("UNDERLYING", weight="bold", size="2", color=COLORS["primary"],
                       font_family=TYPOGRAPHY["font_family"]),
                rx.text(AppState.selected_underlying_symbol, size="1", color=COLORS["text_muted"]),
                rx.text("(3D / 3-min bars)", size="1", color=COLORS["text_muted"]),
                spacing="2",
                align="center",
            ),
            rx.cond(
                AppState.selected_group_id != "",
                rx.plotly(
                    data=AppState.underlying_figure,
                    width="100%",
                    height="230px",
                ),
                rx.text("Select a group to view charts", color=COLORS["text_muted"]),
            ),
            width="100%",
            spacing="2",
        ),
        background=COLORS["bg_panel"],
        border=PANEL_STYLES["border"],
        border_left=PANEL_STYLES["border_left"],
        border_radius=PANEL_STYLES["border_radius"],
        padding=PANEL_STYLES["padding"],
        width="100%",
    )


def combo_price_chart() -> rx.Component:
    """Chart B: Position OHLC candlestick chart (12h, 3min bars) with stop price line."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("POSITION OHLC", weight="bold", size="2", color=COLORS["primary"],
                       font_family=TYPOGRAPHY["font_family"]),
                rx.text("(12h / 3-min bars)", size="1", color=COLORS["text_muted"]),
                rx.spacer(),
                # Live values header (label shows trigger_price_type: Mid, Mark, Bid, Ask, Last)
                rx.hstack(
                    rx.text("Fill:", size="1", color=COLORS["text_muted"]),
                    rx.text(AppState.chart_pos_fill, size="1", weight="bold", color=COLORS["text_secondary"]),
                    rx.text(AppState.chart_trigger_label + ":", size="1", color=COLORS["accent"]),
                    rx.text(AppState.chart_pos_close, size="1", weight="bold", color=COLORS["accent"]),
                    rx.text("Stop:", size="1", color=COLORS["text_muted"]),
                    rx.text(AppState.chart_pos_stop, size="1", weight="bold", color=COLORS["stop"]),
                    rx.text("Limit:", size="1", color=COLORS["text_muted"]),
                    rx.text(AppState.chart_pos_limit, size="1", weight="bold", color=COLORS["limit"]),
                    rx.text("HWM:", size="1", color=COLORS["text_muted"]),
                    rx.text(AppState.chart_pos_hwm, size="1", weight="bold", color=COLORS["hwm"]),
                    spacing="1",
                    align="center",
                ),
                spacing="2",
                width="100%",
                align="center",
            ),
            rx.cond(
                AppState.selected_group_id != "",
                rx.plotly(
                    data=AppState.position_figure,
                    width="100%",
                    height="230px",
                ),
                rx.text("Select a group", color=COLORS["text_muted"]),
            ),
            width="100%",
            spacing="2",
        ),
        background=COLORS["bg_panel"],
        border=PANEL_STYLES["border"],
        border_left=PANEL_STYLES["border_left"],
        border_radius=PANEL_STYLES["border_radius"],
        padding=PANEL_STYLES["padding"],
        width="100%",
    )


def live_oscillator_chart() -> rx.Component:
    """Chart C: P&L history with extremum bundling (12h, 3min bars)."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("P&L HISTORY", weight="bold", size="2", color=COLORS["primary"],
                       font_family=TYPOGRAPHY["font_family"]),
                rx.text("(12h / 3-min bars)", size="1", color=COLORS["text_muted"]),
                rx.spacer(),
                # Live values header
                rx.hstack(
                    rx.text("P&L:", size="1", color=COLORS["text_muted"]),
                    rx.text(AppState.chart_pnl_current, size="1", weight="bold", color=COLORS["text_secondary"]),
                    rx.text("Stop P&L:", size="1", color=COLORS["text_muted"]),
                    rx.text(AppState.chart_pnl_stop, size="1", weight="bold", color=COLORS["stop"]),
                    spacing="1",
                    align="center",
                ),
                spacing="2",
                width="100%",
                align="center",
            ),
            rx.cond(
                AppState.selected_group_id != "",
                rx.plotly(
                    data=AppState.pnl_figure,
                    width="100%",
                    height="230px",
                ),
                rx.text("Select a group", color=COLORS["text_muted"]),
            ),
            width="100%",
            spacing="2",
        ),
        background=COLORS["bg_panel"],
        border=PANEL_STYLES["border"],
        border_left=PANEL_STYLES["border_left"],
        border_radius=PANEL_STYLES["border_radius"],
        padding=PANEL_STYLES["padding"],
        width="100%",
    )


def charts_section() -> rx.Component:
    """Combined charts section for monitor tab."""
    return rx.vstack(
        # Row 1: Underlying chart (full width)
        underlying_chart(),
        # Row 2: Position OHLC (full width)
        combo_price_chart(),
        # Row 3: P&L History (full width)
        live_oscillator_chart(),
        width="100%",
        spacing="3",
    )


def monitor_tab() -> rx.Component:
    """Monitor tab content - Groups overview with charts."""
    return rx.vstack(
        # Groups in 3-column grid with selection
        rx.cond(
            AppState.groups.length() > 0,
            rx.box(
                rx.grid(
                    rx.foreach(AppState.groups, compact_group_card),
                    columns="3",
                    spacing="3",
                    width="100%",
                ),
                width="100%",
            ),
            rx.text("No groups to monitor. Create groups in Setup tab.", color=COLORS["text_muted"]),
        ),
        # Charts section (3 charts: Underlying, Position Price, Live P&L)
        charts_section(),
        width="100%",
        spacing="4",
    )


# =============================================================================
# DELETE CONFIRMATION DIALOG
# =============================================================================

def delete_confirmation_dialog() -> rx.Component:
    """Dialog to confirm group deletion."""
    return rx.cond(
        AppState.delete_confirm_group_id != "",
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Delete Group", color=COLORS["text_primary"]),
                rx.dialog.description(
                    "Do you want to cancel the order at IB or leave it running?",
                    color=COLORS["text_secondary"],
                ),
                rx.hstack(
                    rx.button(
                        "Cancel Order & Delete",
                        on_click=lambda: AppState.confirm_delete_group(True),
                        color_scheme="red",
                    ),
                    rx.button(
                        "Leave Order & Delete",
                        on_click=lambda: AppState.confirm_delete_group(False),
                        color_scheme="orange",
                    ),
                    rx.button(
                        "Cancel",
                        on_click=AppState.cancel_delete,
                        variant="outline",
                    ),
                    spacing="2",
                    justify="end",
                    width="100%",
                ),
                style={
                    "max_width": "400px",
                    "background": COLORS["bg_surface"],
                    "border": CARD_STYLES["border"],
                },
            ),
            open=True,
        ),
        rx.box(),
    )


# =============================================================================
# LEGACY EXPORTS (for backwards compatibility)
# =============================================================================

def connection_panel() -> rx.Component:
    """Legacy - now part of header_panel."""
    return header_panel()


def status_bar() -> rx.Component:
    """Legacy - status is now in tab_navigation."""
    return rx.text(AppState.status_message, size="2", color=COLORS["text_muted"])


def groups_panel() -> rx.Component:
    """Legacy - now split between setup_tab and monitor_tab."""
    return rx.cond(
        AppState.active_tab == "setup",
        rx.vstack(
            rx.heading("Groups", size="4", color=COLORS["text_primary"]),
            rx.foreach(AppState.groups, group_config_card),
            width="100%",
        ),
        rx.vstack(
            rx.foreach(AppState.groups, compact_group_card),
            width="100%",
        ),
    )
