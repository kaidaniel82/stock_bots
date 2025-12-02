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

            # Connection status
            rx.hstack(
                rx.badge(
                    AppState.connection_status,
                    color_scheme=rx.cond(AppState.is_connected, "green", "red"),
                ),
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
    )


# =============================================================================
# SETUP TAB COMPONENTS
# =============================================================================

def position_row(row: list) -> rx.Component:
    """Single position row from computed var."""
    con_id = row[0].to(int)
    con_id_str = row[0]
    pnl_color = row[15]
    is_selected = row[16] == "true"
    qty_usage = row[17]           # e.g., "2/3"
    is_fully_used = row[18] == "true"
    selected_qty = row[19]        # Selected qty for this group

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
        rx.table.cell(row[5]),   # quantity_str
        rx.table.cell(
            rx.text(
                qty_usage,
                color=rx.cond(is_fully_used, COLORS["error"], COLORS["success"]),
                font_weight=rx.cond(is_fully_used, "bold", "normal"),
            )
        ),  # usage (e.g., "2/3")
        # Selected Qty dropdown - shows available quantities (0 to available)
        rx.table.cell(
            rx.cond(
                is_fully_used,
                rx.text("-", color=COLORS["text_muted"]),
                rx.select(
                    row[21].split(","),  # qty_options as comma-separated string -> list
                    value=selected_qty,
                    on_change=AppState.set_position_quantity(con_id_str),
                    size="1",
                ),
            )
        ),
        rx.table.cell(row[6]),   # fill_price
        rx.table.cell(row[7]),   # bid
        rx.table.cell(row[8]),   # mid
        rx.table.cell(row[9]),   # ask
        rx.table.cell(row[10]),  # last
        rx.table.cell(row[11]),  # mark
        rx.table.cell(rx.text(row[14], color=pnl_color)),  # pnl with color
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


def group_config_card(group: dict) -> rx.Component:
    """Full configuration card for a group (Setup tab) - Bloomberg style."""
    group_id = group["id"]
    is_active = group["is_active"]

    return rx.box(
        rx.vstack(
            # Header with name, qty and status
            rx.hstack(
                rx.text(group["name"], size="2", weight="bold", color=COLORS["primary"],
                       font_family=TYPOGRAPHY["font_family"]),
                rx.badge(group["total_qty_str"], color_scheme="blue", size="1"),
                rx.badge(
                    rx.cond(is_active, "ACTIVE", "INACTIVE"),
                    color_scheme=rx.cond(is_active, "green", "gray"),
                ),
                rx.spacer(),
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
                width="100%",
            ),
            # Legs
            rx.box(
                rx.text(group["legs_str"], size="1", white_space="pre-wrap", color=COLORS["text_secondary"]),
                padding="2",
                background=COLORS["bg_elevated"],
                border_radius="6px",
                width="100%",
            ),
            # Prices row - Mid, Mark, Bid/Ask and P&L
            rx.hstack(
                rx.vstack(
                    rx.text("Mid", size="1", color=COLORS["text_muted"]),
                    rx.text(group["mid_value_str"], size="2", weight="bold", color=COLORS["text_primary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Mark", size="1", color=COLORS["text_muted"]),
                    rx.text(group["mark_value_str"], size="2", weight="bold", color=COLORS["text_primary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Bid", size="1", color=COLORS["text_muted"]),
                    rx.text(group["spread_bid_str"], size="2", weight="bold", color=COLORS["bid"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Ask", size="1", color=COLORS["text_muted"]),
                    rx.text(group["spread_ask_str"], size="2", weight="bold", color=COLORS["text_primary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("P&L", size="1", color=COLORS["text_muted"]),
                    rx.text(group["pnl_mark_str"], size="2", weight="bold", color=group["pnl_color"]),
                    align="center",
                    spacing="0",
                ),
                spacing="4",
                width="100%",
            ),
            # Greeks row
            rx.hstack(
                rx.vstack(
                    rx.text("Delta", size="1", color=COLORS["text_muted"]),
                    rx.text(group["delta_str"], size="1", weight="bold", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Gamma", size="1", color=COLORS["text_muted"]),
                    rx.text(group["gamma_str"], size="1", weight="bold", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Theta", size="1", color=COLORS["text_muted"]),
                    rx.text(group["theta_str"], size="1", weight="bold", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Vega", size="1", color=COLORS["text_muted"]),
                    rx.text(group["vega_str"], size="1", weight="bold", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                spacing="4",
                width="100%",
            ),
            # Trailing Stop Config
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
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Trail", size="1", color=COLORS["text_muted"]),
                    rx.input(
                        value=group["trail_value"].to(str),
                        on_change=AppState.update_group_trail(group_id),
                        width="50px",
                        size="1",
                    ),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Trigger", size="1", color=COLORS["text_muted"]),
                    rx.select(
                        ["mark", "mid", "bid", "ask", "last"],
                        value=group["trigger_price_type"],
                        on_change=AppState.update_group_trigger_price_type(group_id),
                        size="1",
                    ),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Type", size="1", color=COLORS["text_muted"]),
                    rx.select(
                        ["market", "limit"],
                        value=group["stop_type"],
                        on_change=AppState.update_group_stop_type(group_id),
                        size="1",
                    ),
                    align="center",
                    spacing="0",
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
                        align="center",
                        spacing="0",
                    ),
                    rx.box(),
                ),
                spacing="3",
                width="100%",
            ),
            # HWM and Stop
            rx.hstack(
                rx.vstack(
                    rx.text("HWM", size="1", color=COLORS["text_muted"]),
                    rx.text(group["hwm_str"], size="2", weight="bold", color=COLORS["hwm"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Stop", size="1", color=COLORS["text_muted"]),
                    rx.text(group["stop_str"], size="2", weight="bold", color=COLORS["stop"]),
                    align="center",
                    spacing="0",
                ),
                spacing="4",
            ),
            # Time Exit
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
            spacing="2",
        ),
        background=COLORS["bg_panel"],
        border=PANEL_STYLES["border"],
        border_left=PANEL_STYLES["border_left"],
        border_radius=PANEL_STYLES["border_radius"],
        padding=PANEL_STYLES["padding"],
        width="100%",
    )


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

def compact_group_card(group: dict) -> rx.Component:
    """Compact group card for monitor view (2x2 grid) - Bloomberg style."""
    group_id = group["id"]
    is_active = group["is_active"]

    return rx.box(
        rx.vstack(
            # Header with name, qty and status
            rx.hstack(
                rx.text(group["name"], weight="bold", size="2", color=COLORS["primary"],
                       font_family=TYPOGRAPHY["font_family"]),
                rx.badge(group["total_qty_str"], color_scheme="blue", size="1"),
                rx.badge(
                    rx.cond(is_active, "ACTIVE", "IDLE"),
                    color_scheme=rx.cond(is_active, "green", "gray"),
                    size="1",
                ),
                width="100%",
            ),
            # Key metrics - Mid, Mark, Bid, Ask, P&L
            rx.hstack(
                rx.vstack(
                    rx.text("Mid", size="1", color=COLORS["text_muted"]),
                    rx.text(group["mid_value_str"], size="1", weight="bold", color=COLORS["text_primary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Mark", size="1", color=COLORS["text_muted"]),
                    rx.text(group["mark_value_str"], size="1", weight="bold", color=COLORS["text_primary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Bid", size="1", color=COLORS["text_muted"]),
                    rx.text(group["spread_bid_str"], size="1", weight="bold", color=COLORS["bid"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Ask", size="1", color=COLORS["text_muted"]),
                    rx.text(group["spread_ask_str"], size="1", weight="bold", color=COLORS["text_primary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("P&L", size="1", color=COLORS["text_muted"]),
                    rx.text(group["pnl_mark_str"], size="1", weight="bold", color=group["pnl_color"]),
                    align="center",
                    spacing="0",
                ),
                spacing="2",
                width="100%",
            ),
            # Greeks row
            rx.hstack(
                rx.vstack(
                    rx.text("Delta", size="1", color=COLORS["text_muted"]),
                    rx.text(group["delta_str"], size="1", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Gamma", size="1", color=COLORS["text_muted"]),
                    rx.text(group["gamma_str"], size="1", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Theta", size="1", color=COLORS["text_muted"]),
                    rx.text(group["theta_str"], size="1", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Vega", size="1", color=COLORS["text_muted"]),
                    rx.text(group["vega_str"], size="1", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                spacing="2",
                width="100%",
            ),
            # HWM and Stop
            rx.hstack(
                rx.vstack(
                    rx.text("HWM", size="1", color=COLORS["text_muted"]),
                    rx.text(group["hwm_str"], size="1", color=COLORS["hwm"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Stop", size="1", color=COLORS["text_muted"]),
                    rx.text(group["stop_str"], size="1", color=COLORS["stop"]),
                    align="center",
                    spacing="0",
                ),
                rx.vstack(
                    rx.text("Trail", size="1", color=COLORS["text_muted"]),
                    rx.text(group["trail_display"], size="1", color=COLORS["text_secondary"]),
                    align="center",
                    spacing="0",
                ),
                spacing="3",
                width="100%",
            ),
            # Action buttons
            rx.hstack(
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


def chart_placeholder() -> rx.Component:
    """Placeholder for future chart implementation - Bloomberg style."""
    return rx.box(
        rx.vstack(
            rx.text("CHART", weight="bold", size="2", color=COLORS["primary"],
                   font_family=TYPOGRAPHY["font_family"]),
            rx.box(
                rx.text("Price chart coming soon...", color=COLORS["text_muted"],
                       font_family=TYPOGRAPHY["font_family"]),
                height="200px",
                width="100%",
                display="flex",
                align_items="center",
                justify_content="center",
                background=COLORS["bg_elevated"],
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


def monitor_tab() -> rx.Component:
    """Monitor tab content - Groups overview with charts."""
    return rx.vstack(
        # Groups in 3-column grid
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
        # Chart section
        chart_placeholder(),
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
