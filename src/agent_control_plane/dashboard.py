"""FastAPI dashboard for Agent Control Plane."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from agent_control_plane.analytics import (
    get_cost_timeseries,
    get_fleet_health_timeseries,
    get_health_timeseries,
)
from agent_control_plane.inventory import (
    get_agent,
    get_connection,
    get_health_history,
    get_summary_stats,
    list_agents,
    list_cost_records,
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
    _html_login = _read_template("login.html")
    _html_shadow = _read_template("shadow.html")
    _html_notifications = _read_template("notifications.html")
    _html_notification_settings = _read_template("notification_settings.html")

    # ------------------------------------------------------------------
    # Auth Routes
    # ------------------------------------------------------------------

    _SESSION_COOKIE = "acp_session"

    def _get_session_user(request: Request):
        """Get authenticated user from session cookie."""
        from agent_control_plane.auth import get_session_user
        token = request.cookies.get(_SESSION_COOKIE)
        if not token:
            return None
        return get_session_user(token)

    @app.post("/api/login")
    async def api_login(request: Request):
        """Authenticate user and set session cookie."""
        from agent_control_plane.auth import authenticate_email, create_session

        body = await request.json()
        email = body.get("email", "")
        api_key = body.get("api_key", "")

        user = authenticate_email(email, api_key)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid email or API key")

        token = create_session(user.name)
        response = JSONResponse({"status": "ok", "user": user.name, "role": user.role.value})
        response.set_cookie(
            key=_SESSION_COOKIE,
            value=token,
            max_age=86400,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.post("/api/logout")
    def api_logout():
        """Clear session cookie."""
        response = JSONResponse({"status": "ok"})
        response.delete_cookie(key=_SESSION_COOKIE)
        return response

    @app.get("/api/me")
    def api_me(request: Request):
        """Get current session info."""
        user = _get_session_user(request)
        if user is None:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "user": user.name,
            "role": user.role.value,
            "single_user_mode": False,
        }

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        """Login page."""
        return HTMLResponse(content=_html_login)

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page():
        """Admin panel (minimal)."""
        # Read the admin template or just inline it
        return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Admin — ACP</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root { --bg: #0f1117; --bg-card: #1a1d27; --text: #e1e4ed; --text-dim: #8b8fa3; --border: #2a2d3a; --accent: #6366f1; }
  body { font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; }
  h1 { margin-bottom: 1.5rem; }
  table { width: 100%; border-collapse: collapse; background: var(--bg-card); border-radius: 8px; overflow: hidden; }
  th, td { padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { font-size: 0.75rem; text-transform: uppercase; color: var(--text-dim); }
  a { color: var(--accent); text-decoration: none; }
  .section { margin-bottom: 2rem; }
</style></head>
<body>
  <h1>Admin Panel</h1>
  <div class="section" id="users-section">
    <h2>Users</h2>
    <table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Created</th></tr></thead>
    <tbody id="users-tbody"><tr><td colspan="4" class="loading">Loading...</td></tr></tbody></table>
  </div>
  <div class="section" id="teams-section">
    <h2>Teams</h2>
    <table><thead><tr><th>ID</th><th>Name</th><th>Description</th><th>Members</th></tr></thead>
    <tbody id="teams-tbody"><tr><td colspan="4" class="loading">Loading...</td></tr></tbody></table>
  </div>
  <p><a href="/">← Back to Dashboard</a></p>
  <script>
    async function loadAdmin() {
      try {
        const [usersRes, teamsRes] = await Promise.all([
          fetch('/api/admin/users'),
          fetch('/api/admin/teams'),
        ]);
        const users = await usersRes.json();
        const teams = await teamsRes.json();
        const usersBody = document.getElementById('users-tbody');
        if (users.users && users.users.length > 0) {
          usersBody.innerHTML = users.users.map(u => `<tr><td>${u.name}</td><td>${u.email}</td><td>${u.role}</td><td>${u.created_at?.slice(0,10) || ''}</td></tr>`).join('');
        } else {
          usersBody.innerHTML = '<tr><td colspan="4" class="empty">No users</td></tr>';
        }
        const teamsBody = document.getElementById('teams-tbody');
        if (teams.teams && teams.teams.length > 0) {
          teamsBody.innerHTML = teams.teams.map(t => `<tr><td>${t.id}</td><td>${t.name}</td><td>${t.description}</td><td>${t.member_count || 0}</td></tr>`).join('');
        } else {
          teamsBody.innerHTML = '<tr><td colspan="4" class="empty">No teams</td></tr>';
        }
      } catch(e) {
        document.getElementById('users-tbody').innerHTML = '<tr><td colspan="4" class="error">Failed to load</td></tr>';
      }
    }
    loadAdmin();
  </script>
</body></html>""")

    # ------------------------------------------------------------------
    # Admin API endpoints
    # ------------------------------------------------------------------

    @app.get("/api/admin/users")
    def api_admin_users():
        """List all users (admin)."""
        from agent_control_plane.inventory import list_users
        conn = _conn()
        users = list_users(conn)
        conn.close()
        return {"users": [
            {"name": u.name, "email": u.email, "role": u.role.value,
             "created_at": u.created_at.isoformat()}
            for u in users
        ]}

    @app.get("/api/admin/teams")
    def api_admin_teams():
        """List all teams with member counts (admin)."""
        from agent_control_plane.inventory import list_team_members, list_teams
        conn = _conn()
        teams = list_teams(conn)
        result = []
        for t in teams:
            members = list_team_members(conn, t.id)
            result.append({
                "id": t.id, "name": t.name, "description": t.description,
                "member_count": len(members),
            })
        conn.close()
        return {"teams": result}

    # ------------------------------------------------------------------
    # Shadow AI Routes (Sprint S-8)
    # ------------------------------------------------------------------

    @app.get("/api/shadow")
    def api_shadow():
        """List discovered shadow IT services."""
        from agent_control_plane.inventory import list_shadow_services
        conn = _conn()
        services = list_shadow_services(conn)
        conn.close()
        return {
            "services": [
                {
                    "id": s.id, "name": s.name, "url": s.url,
                    "service_type": s.service_type, "risk": s.risk,
                    "host": s.host, "port": s.port,
                    "first_seen": s.first_seen.isoformat() if s.first_seen else None,
                }
                for s in services
            ],
        }

    @app.get("/api/shadow/summary")
    def api_shadow_summary():
        """Shadow IT risk summary."""
        from agent_control_plane.inventory import get_shadow_summary
        conn = _conn()
        summary = get_shadow_summary(conn)
        conn.close()
        return {"summary": summary}

    @app.get("/shadow", response_class=HTMLResponse)
    def shadow_page():
        """Shadow AI discovery page."""
        return HTMLResponse(content=_html_shadow)

    @app.get("/notifications", response_class=HTMLResponse)
    def notifications_page():
        """Notification history page."""
        return HTMLResponse(content=_html_notifications)

    @app.get("/notification-settings", response_class=HTMLResponse)
    def notification_settings_page():
        """Notification settings page."""
        return HTMLResponse(content=_html_notification_settings)

    # ------------------------------------------------------------------
    # HTML Page Routes
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
            ],
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
    # Drift Detection API Routes (Sprint S-6)
    # ------------------------------------------------------------------

    @app.get("/api/drift/summary")
    def api_drift_summary():
        """Drift event summary by severity."""
        from agent_control_plane.inventory import get_drift_summary
        conn = _conn()
        summary = get_drift_summary(conn)
        conn.close()
        return {"summary": summary}

    @app.get("/api/drift")
    def api_drift(limit: int = 50, agent: str | None = None, severity: str | None = None):
        """Drift detection history."""
        from agent_control_plane.inventory import get_drift_history
        conn = _conn()
        history = get_drift_history(conn, agent_name=agent, severity=severity, limit=limit)
        conn.close()
        return {
            "drift_events": [
                {
                    "id": d.id,
                    "agent_name": d.agent_name,
                    "field_name": d.field_name,
                    "expected": d.expected,
                    "actual": d.actual,
                    "severity": d.severity,
                    "message": d.message,
                    "detected_at": d.detected_at.isoformat(),
                }
                for d in history
            ],
            "count": len(history),
        }

    @app.get("/api/drift/{agent_name}")
    def api_drift_agent(agent_name: str, limit: int = 50):
        """Drift history for a specific agent."""
        from agent_control_plane.inventory import get_drift_history
        conn = _conn()
        history = get_drift_history(conn, agent_name=agent_name, limit=limit)
        conn.close()
        return {
            "agent_name": agent_name,
            "drift_events": [
                {
                    "id": d.id,
                    "field_name": d.field_name,
                    "expected": d.expected,
                    "actual": d.actual,
                    "severity": d.severity,
                    "message": d.message,
                    "detected_at": d.detected_at.isoformat(),
                }
                for d in history
            ],
            "count": len(history),
        }

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
    # Notification Integration Hub Routes (Sprint S-9)
    # ------------------------------------------------------------------

    @app.get("/api/notification-settings")
    def api_notification_settings():
        """Get current notification channel configuration."""
        from agent_control_plane.alerts.rules import load_alert_config
        cfg = load_alert_config()
        return {"channels": cfg.get("channels", {})}

    @app.put("/api/notification-settings")
    async def api_update_notification_settings(request: Request):
        """Update notification channel configuration."""
        import yaml

        from agent_control_plane.alerts.engine import _reset_config_cache
        from agent_control_plane.config import _resolve_config_path

        body = await request.json()
        cfg_path = _resolve_config_path()
        if not cfg_path or not cfg_path.exists():
            raise HTTPException(status_code=404, detail="Config file not found")

        raw = cfg_path.read_text()
        cfg = yaml.safe_load(raw) or {}

        if "channels" in body:
            if "alerts" not in cfg:
                cfg["alerts"] = {}
            cfg["alerts"]["channels"] = body["channels"]

        cfg_path.write_text(yaml.dump(cfg, default_flow_style=False))
        _reset_config_cache()
        return {"status": "ok"}

    @app.get("/api/notifications")
    def api_notifications(
        channel: str | None = None,
        agent_name: str | None = None,
        alert_type: str | None = None,
        success: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Notification history with filters."""
        from agent_control_plane.notifications.service import get_notification_history

        success_bool: bool | None = None
        if success is not None:
            success_bool = success in ("1", "true", "True")

        notifications = get_notification_history(
            channel=channel or None,
            agent_name=agent_name or None,
            alert_type=alert_type or None,
            success=success_bool,
            limit=min(limit, 200),
            offset=offset,
        )
        return {"notifications": notifications, "count": len(notifications)}

    @app.get("/api/notifications/summary")
    def api_notifications_summary():
        """Notification summary counts."""
        from agent_control_plane.notifications.service import get_notification_summary
        return get_notification_summary()

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
    uvicorn.run(app, host=host, port=port, log_level="info")
