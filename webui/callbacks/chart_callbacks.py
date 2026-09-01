"""
Chart-related callbacks for TradingAgents WebUI
Enhanced with symbol-based pagination
"""

from dash import Input, Output, State, ctx, html, ALL, dash
from datetime import datetime

from webui.utils.state import app_state
from webui.utils.charts import create_chart, create_welcome_chart


def create_symbol_button(symbol, index, is_active=False):
    """Create a symbol button for pagination.

    Styled as a segment of the shared segmented control rather than a Bootstrap
    button, so the symbol pager and the range strip beside it read as one row.
    """
    return html.Button(
        symbol,
        id={"type": "symbol-btn", "index": index, "component": "charts"},
        className=f"seg-btn symbol-btn{' active' if is_active else ''}",
        n_clicks=0,
    )


def register_chart_callbacks(app):
    """Register all chart-related callbacks including symbol pagination"""
    
    @app.callback(
        Output("chart-pagination-container", "children"),
        [Input("app-store", "data"),
         Input("refresh-interval", "n_intervals"),
         Input("ticker-input", "value")]
    )
    def update_chart_symbol_pagination(store_data, n_intervals, ticker_text):
        """Update the symbol pagination buttons for charts"""
        # symbol_states only fills once a run starts. Before that, fall back to
        # what the user has typed, so selecting three symbols does not leave the
        # chart reporting "No symbols available" next to them.
        symbols = list(app_state.symbol_states.keys())
        if not symbols:
            symbols = [
                part.strip().upper()
                for part in str(ticker_text or "").split(",")
                if part.strip()
            ]
        if not symbols:
            return html.Div(
                "Add a symbol to preview its chart",
                className="text-faint",
                style={"padding": "8px", "fontSize": "12px"},
            )

        current_symbol = app_state.current_symbol
        
        # Find active symbol index
        active_index = 0
        if current_symbol and current_symbol in symbols:
            active_index = symbols.index(current_symbol)
        
        buttons = []
        for i, symbol in enumerate(symbols):
            is_active = i == active_index
            buttons.append(create_symbol_button(symbol, i, is_active))
        
        if len(symbols) > 1:
            # Add navigation info
            nav_info = html.Div(
                f"{len(symbols)} symbols under analysis",
                className="text-faint",
                style={"fontSize": "11px", "marginTop": "6px"},
            )

            return html.Div(
                [html.Div(buttons, className="segmented wrap"), nav_info],
                className="symbol-pagination-wrapper",
            )
        else:
            return html.Div(buttons, className="segmented")

    @app.callback(
        [Output("chart-pagination", "active_page", allow_duplicate=True),
         Output("report-pagination", "active_page", allow_duplicate=True),
         Output("chart-pagination-container", "children", allow_duplicate=True)],
        [Input({"type": "symbol-btn", "index": ALL, "component": "charts"}, "n_clicks")],
        prevent_initial_call=True
    )
    def handle_chart_symbol_click(symbol_clicks):
        """Handle symbol button clicks for charts with immediate visual feedback"""
        if not any(symbol_clicks) or not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update
        
        # Find which button was clicked
        button_id = ctx.triggered[0]["prop_id"]
        if "symbol-btn" in button_id:
            # Extract index from the button ID
            import json
            button_data = json.loads(button_id.split('.')[0])
            clicked_index = button_data["index"]
            
            # Update current symbol
            symbols = list(app_state.symbol_states.keys())
            if 0 <= clicked_index < len(symbols):
                app_state.current_symbol = symbols[clicked_index]
                page_number = clicked_index + 1
                
                # ⚡ IMMEDIATE BUTTON UPDATE - No waiting for refresh!
                buttons = []
                for i, symbol in enumerate(symbols):
                    is_active = i == clicked_index  # Active state based on click
                    buttons.append(create_symbol_button(symbol, i, is_active))
                
                if len(symbols) > 1:
                    # Add navigation info
                    nav_info = html.Div(
                        f"{len(symbols)} symbols under analysis",
                        className="text-faint",
                        style={"fontSize": "11px", "marginTop": "6px"},
                    )

                    button_container = html.Div(
                        [html.Div(buttons, className="segmented wrap"), nav_info],
                        className="symbol-pagination-wrapper",
                    )
                else:
                    button_container = html.Div(buttons, className="segmented")
                
                return page_number, page_number, button_container
        
        return dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        [Output("chart-container", "figure"),
         Output("current-symbol-display", "children"),
         Output("chart-store", "data")],
        [Input("period-1d", "n_clicks"),
         Input("period-1w", "n_clicks"),
         Input("period-1mo", "n_clicks"),
         Input("period-1y", "n_clicks"),
         Input("chart-pagination", "active_page"),
         Input("manual-chart-refresh", "n_clicks")],
        [State("chart-store", "data")]
    )
    def update_chart(n_1d, n_1w, n_1mo, n_1y, active_page, manual_refresh, chart_store_data):
        """Update the chart based on period selection or ticker change"""
        # print(f"[CHART] Called with active_page={active_page}, symbol_states={list(app_state.symbol_states.keys()) if app_state.symbol_states else []}")
        
        if not app_state.symbol_states or not active_page:
            # print(f"[CHART] No symbol states or no active page, returning welcome chart")
            return create_welcome_chart(), "", chart_store_data

        # Safeguard against accessing invalid page index (e.g., after page refresh)
        symbols_list = list(app_state.symbol_states.keys())
        if active_page > len(symbols_list):
            # print(f"[CHART] Page index {active_page} out of range for {len(symbols_list)} symbols")
            return create_welcome_chart(), "Page index out of range", chart_store_data

        symbol = symbols_list[active_page - 1]
        # print(f"[CHART] Selected symbol: {symbol} (page {active_page})")

        # Determine which input triggered the callback
        triggered_prop = ctx.triggered[0]["prop_id"] if ctx.triggered else None
        # print(f"[CHART] Triggered by: {triggered_prop}")

        # Default period handling
        period_map = {
            "period-1d.n_clicks": "1d",
            "period-1w.n_clicks": "1w",
            "period-1mo.n_clicks": "1mo",
            "period-1y.n_clicks": "1y"
        }

        # Determine selected period
        selected_period = None
        if triggered_prop in period_map:
            selected_period = period_map[triggered_prop]
        elif chart_store_data and "selected_period" in chart_store_data:
            selected_period = chart_store_data["selected_period"]
        else:
            selected_period = "1y"  # Default to 1Y to match button default

        # print(f"[CHART] Using period: {selected_period}")

        # Create chart
        try:
            chart_figure = create_chart(symbol, selected_period)
            symbol_display = symbol.upper()
            
            # Update store data
            updated_store_data = chart_store_data or {}
            updated_store_data["selected_period"] = selected_period
            updated_store_data["last_symbol"] = symbol
            updated_store_data["last_updated"] = datetime.now().isoformat()
            
            # print(f"[CHART] Successfully created chart for {symbol} with period {selected_period}")
            return chart_figure, symbol_display, updated_store_data
            
        except Exception as e:
            # print(f"[CHART] Error creating chart for {symbol}: {e}")
            return create_welcome_chart(), f"Could not load {symbol.upper()}", chart_store_data

    @app.callback(
        Output("chart-last-updated", "children"),
        [Input("chart-store", "data")]
    )
    def update_chart_timestamp(chart_store_data):
        """Update the chart last updated timestamp"""
        if not chart_store_data or "last_updated" not in chart_store_data:
            return ""
        
        try:
            last_updated = datetime.fromisoformat(chart_store_data["last_updated"])
            return f"updated {last_updated.strftime('%I:%M:%S %p')}"
        except:
            return ""

    @app.callback(
        [Output("period-1d", "active"),
         Output("period-1w", "active"),
         Output("period-1mo", "active"),
         Output("period-1y", "active")],
        [Input("period-1d", "n_clicks"),
         Input("period-1w", "n_clicks"),
         Input("period-1mo", "n_clicks"),
         Input("period-1y", "n_clicks")]
    )
    def update_active_period_button(n_1d, n_1w, n_1mo, n_1y):
        """Update which period button is active"""
        button_id = ctx.triggered_id if ctx.triggered_id else "period-1y"
        
        return (
            button_id == "period-1d",
            button_id == "period-1w", 
            button_id == "period-1mo",
            button_id == "period-1y"
        ) 