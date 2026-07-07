"""FastAPI dashboard for Agent Control Plane."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from agent_control_plane.config import get_home
from agent_control_plane.inventory import (
    get_connection,
    get_agent,
    get_health_history,
    get_summary_stats,
    list_agents,
    list_cost_records,
)
from agent_control_plane.analytics import (
    get_health_timeseries,
    get_fleet_health_timeseries,
    get_cost_timeseries,
)


def _read_template(name: str) -> str:
    """Read an HTML template file from the templates directory."""
    pkg_dir = Path(__file__).parent
    template_path = pkg_dir / "templates" / name
    return template_path.read_text()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Control Plane",
        version="0.1.0",
        description="AI Agent Operations Platform Dashboard",
    )

    # Capture DB path at creation time so TestClient threads work
    from agent_control_plane.config import get_db_path
    _db_path = get_db_path()

    def _conn():
        return get_connection(_db_path)

    # Add CORS middleware BEFORE routes
    from starlette.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Cache templates in memory
    _html_dashboard = _read_template("dashboard.html")
    _html_agents = _read_template("agents.html")
    _html_agent_detail_base = _read_template("agent_detail.html")
    _html_costs = _read_template("costs.html")
    _html_404 = _read_template("404.html")

    # ------------------------------------------------------------------
    # API Routes
    # ------------------------------------------------------------------

    @app.get("/api/status")
    def api_status():
        """Fleet status summary."""
        conn = _conn()
        stats = get_summary_stats(conn)
        conn.close()
        return {
            "total_agents": stats.total_agents,
            "online": stats.online,
            "offline": stats.offline,
            "degraded": stats.degraded,
            "unknown": stats.unknown,
            "total_estimated_cost_monthly_usd": stats.total_estimated_cost_monthly_usd,
            "total_checks_run": stats.total_checks_run,
        }

    @app.get("/api/agents")
    def api_agents():
        """List all agents."""
        conn = _conn()
        agents = list_agents(conn)
        conn.close()
        return {
            "agents": [
                {
                    "name": a.name,
                    "url": a.url,
                    "provider": a.provider,
                    "status": a.status.value,
                    "tags": a.tags,
                    "first_seen": a.first_seen.isoformat(),
                    "last_seen": a.last_seen.isoformat(),
                    "total_checks": a.total_checks,
                    "successful_checks": a.successful_checks,
                    "avg_response_time_ms": round(a.avg_response_time_ms, 2),
                }
                for a in agents
            ]
        }

    @app.get("/api/agents/{name}/health")
    def api_agent_health(name: str):
        """Health check history for a specific agent."""
        conn = _conn()
        agent = get_agent(conn, name)
        if agent is None:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        history = get_health_history(conn, name)
        conn.close()
        return {
            "agent_name": name,
            "health_log": [
                {
                    "id": h["id"],
                    "status": h["status"],
                    "response_time_ms": h["response_time_ms"],
                    "status_code": h["status_code"],
                    "error": h["error"],
                    "timestamp": h["timestamp"],
                }
                for h in history
            ],
        }

    @app.get("/api/costs")
    def api_costs():
        """Cost breakdown per agent."""
        conn = _conn()
        costs = list_cost_records(conn)
        conn.close()
        return {
            "costs": [
                {
                    "agent_name": c.agent_name,
                    "month": c.month,
                    "estimated_tokens_in": c.estimated_tokens_in,
                    "estimated_tokens_out": c.estimated_tokens_out,
                    "estimated_cost_usd": c.estimated_cost_usd,
                }
                for c in costs
            ],
            "total_monthly_cost": sum(c.estimated_cost_usd for c in costs),
        }

    @app.get("/api/export")
    def api_export():
        """Full inventory export as JSON."""
        from agent_control_plane.exporter import build_export_data
        data = build_export_data(db_path=_db_path)
        return JSONResponse(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=acp-inventory.json"},
        )

    @app.get("/api/alerts")
    def api_alerts(limit: int = 50, agent: str | None = None):
        """Alert history."""
        from agent_control_plane.alerts.history import get_alert_history
        history = get_alert_history(agent_name=agent, limit=limit)
        return {"alerts": history, "count": len(history)}

    # ------------------------------------------------------------------
    # Analytics API Routes (Sprint S-5)
    # ------------------------------------------------------------------

    @app.get("/api/analytics/health/{agent_name}")
    def api_analytics_health_agent(agent_name: str, bucket: str = "day", days: int = 7):
        """Health time-series for a specific agent."""
        conn = _conn()
        agent = get_agent(conn, agent_name)
        if agent is None:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        series = get_health_timeseries(conn, agent_name, bucket=bucket, days=days)
        conn.close()
        return {"agent_name": agent_name, "bucket": bucket, "series": series}

    @app.get("/api/analytics/health")
    def api_analytics_health_fleet(bucket: str = "day", days: int = 7):
        """Fleet-level health time-series aggregated across all agents."""
        conn = _conn()
        series = get_fleet_health_timeseries(conn, bucket=bucket, days=days)
        conn.close()
        return {"bucket": bucket, "days": days, "series": series}

    @app.get("/api/analytics/costs")
    def api_analytics_costs(months: int = 6, agent: str | None = None):
        """Cost time-series grouped by month."""
        conn = _conn()
        series = get_cost_timeseries(conn, months=months, agent_name=agent)
        conn.close()
        return {"months": months, "series": series}

    @app.get("/metrics")
    def prometheus_metrics():
        """Prometheus metrics endpoint — agent health in text format."""
        conn = _conn()
        agents = list_agents(conn)
        stats = get_summary_stats(conn)
        conn.close()

        lines = [
            "# HELP acp_agent_online Current online status of AI agents (1=online, 0=offline)",
            "# TYPE acp_agent_online gauge",
        ]
        for a in agents:
            lines.append(f'acp_agent_online{{name="{a.name}",provider="{a.provider}"}} {1 if a.status.value == "online" else 0}')

        lines.append("")
        lines.append("# HELP acp_agent_response_ms Average response time in milliseconds")
        lines.append("# TYPE acp_agent_response_ms gauge")
        for a in agents:
            lines.append(f'acp_agent_response_ms{{name="{a.name}"}} {a.avg_response_time_ms}')

        lines.append("")
        lines.append("# HELP acp_agent_checks_total Total health checks performed")
        lines.append("# TYPE acp_agent_checks_total counter")
        for a in agents:
            lines.append(f'acp_agent_checks_total{{name="{a.name}"}} {a.total_checks}')

        lines.append("")
        lines.append("# HELP acp_agent_checks_successful Successful health checks")
        lines.append("# TYPE acp_agent_checks_successful counter")
        for a in agents:
            lines.append(f'acp_agent_checks_successful{{name="{a.name}"}} {a.successful_checks}')

        lines.append("")
        lines.append("# HELP acp_fleet_agents_total Total number of agents in inventory")
        lines.append("# TYPE acp_fleet_agents_total gauge")
        lines.append(f"acp_fleet_agents_total {stats.total_agents}")

        lines.append("")
        lines.append("# HELP acp_fleet_monthly_cost_est Estimated monthly cost for all agents (USD)")
        lines.append("# TYPE acp_fleet_monthly_cost_est gauge")
        lines.append(f"acp_fleet_monthly_cost_est {stats.total_estimated_cost_monthly_usd}")

        return PlainTextResponse("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # HTML Page Routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard_page():
        """Main dashboard page."""
        return HTMLResponse(content=_html_dashboard)

    @app.get("/agents", response_class=HTMLResponse)
    def agents_page():
        """Agent list page."""
        return HTMLResponse(content=_html_agents)

    @app.get("/agents/{name}", response_class=HTMLResponse)
    def agent_detail_page(name: str):
        """Agent detail page."""
        conn = _conn()
        agent = get_agent(conn, name)
        conn.close()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return HTMLResponse(content=_html_agent_detail_base.replace("{{ agent_name }}", name))

    @app.get("/costs", response_class=HTMLResponse)
    def costs_page():
        """Cost breakdown page."""
        return HTMLResponse(content=_html_costs)

    # ------------------------------------------------------------------
    # Error Handling
    # ------------------------------------------------------------------

    @app.exception_handler(404)
    async def not_found_handler(request, exc):
        return HTMLResponse(content=_html_404, status_code=404)

    return app


def serve_dashboard(host: str = "127.0.0.1", port: int = 8337) -> None:
    """Start the dashboard server."""
    import uvicorn
    app = create_app()
    print(f"  Agent Control Plane Dashboard → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
