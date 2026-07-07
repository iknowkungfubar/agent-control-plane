"""CLI interface for the Agent Control Plane."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_control_plane import __version__
from agent_control_plane.config import get_home
from agent_control_plane.cost_tracker import get_all_costs, total_monthly_cost
from agent_control_plane.discovery import get_configured_agents, scan_and_report
from agent_control_plane.exporter import export_csv, export_json
from agent_control_plane.health import run_health_checks
from agent_control_plane.inventory import get_connection, get_summary_stats, list_agents
from agent_control_plane.models import AgentStatus, DriftSeverity

console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-control-plane",
        description="AI Agent Operations Platform — discover, inventory, monitor, and track costs for AI agents.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="command", help="Command to execute")

    # scan
    sub.add_parser("scan", help="Discover and register configured agents in inventory")

    # list
    sub.add_parser("list", help="List all agents in inventory")

    # health
    health_p = sub.add_parser("health", help="Run health checks against all agents")
    health_p.add_argument(
        "--timeout", type=float, default=5.0,
        help="HTTP timeout per check in seconds (default: 5.0)",
    )

    # cost
    sub.add_parser("cost", help="Show estimated costs for all agents")

    # export
    export_p = sub.add_parser("export", help="Export inventory to file")
    export_p.add_argument(
        "--format", choices=["json", "csv"], default="json",
        help="Export format (default: json)",
    )
    export_p.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output file path (default: auto-named in ACP_HOME)",
    )

    # status
    sub.add_parser("status", help="Show summary statistics for the agent fleet")

    # discover
    discover_p = sub.add_parser("discover", help="Auto-discover AI agents on a host")
    discover_p.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Host to scan (default: 127.0.0.1)",
    )
    discover_p.add_argument(
        "--ports", type=str, default=None,
        help="Port(s) to scan, comma-separated or range (default: 11434,8080,8000,5000,3000)",
    )
    discover_p.add_argument(
        "--register", action="store_true",
        help="Register discovered agents into inventory",
    )
    discover_p.add_argument(
        "--timeout", type=float, default=2.0,
        help="HTTP probe timeout per port (default: 2.0s)",
    )

    # delete
    delete_p = sub.add_parser("delete", help="Remove an agent from inventory")
    delete_p.add_argument("name", type=str, help="Agent name to delete")

    # dashboard
    dash_p = sub.add_parser("dashboard", help="Start the web UI dashboard")
    dash_p.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    dash_p.add_argument(
        "--port", "-p", type=int, default=8337,
        help="Port to bind to (default: 8337)",
    )

    # config-baseline
    cb_p = sub.add_parser("config-baseline", help="Manage agent configuration baselines")
    cb_sub = cb_p.add_subparsers(dest="config_baseline_command", help="Baseline sub-command")

    cb_capture = cb_sub.add_parser("capture", help="Capture baseline from live agent")
    cb_capture.add_argument("name", type=str, help="Agent name")
    cb_capture.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout (default: 5.0s)")

    cb_set = cb_sub.add_parser("set", help="Manually set baseline values")
    cb_set.add_argument("name", type=str, help="Agent name")
    cb_set.add_argument("--provider", type=str, default=None, help="Expected provider")
    cb_set.add_argument("--health-path", type=str, default=None, help="Expected health check path")
    cb_set.add_argument("--version", type=str, default=None, help="Expected version")
    cb_set.add_argument("--tags", type=str, default=None, help="Expected tags (comma-separated)")

    cb_show = cb_sub.add_parser("show", help="Show baseline for an agent")
    cb_show.add_argument("name", type=str, help="Agent name")

    cb_list = cb_sub.add_parser("list", help="List all baselines")

    cb_del = cb_sub.add_parser("delete", help="Delete a baseline")
    cb_del.add_argument("name", type=str, help="Agent name")

    # drift-check
    drift_p = sub.add_parser("drift-check", help="Check agents for configuration drift")
    drift_p.add_argument("--name", type=str, default=None, help="Check specific agent only")
    drift_p.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout (default: 5.0s)")

    # drift-report
    sub.add_parser("drift-report", help="Show drift detection history")

    # user commands
    user_p = sub.add_parser("user", help="Manage users")
    user_sub = user_p.add_subparsers(dest="user_command", help="User sub-command")

    user_create = user_sub.add_parser("create", help="Create a new user")
    user_create.add_argument("name", type=str, help="User name")
    user_create.add_argument("--email", type=str, required=True, help="Email address")
    user_create.add_argument("--role", type=str, default="viewer",
                             choices=["admin", "operator", "viewer"], help="User role")

    user_sub.add_parser("list", help="List all users")

    user_del = user_sub.add_parser("delete", help="Delete a user")
    user_del.add_argument("name", type=str, help="User name to delete")

    # team commands
    team_p = sub.add_parser("team", help="Manage teams")
    team_sub = team_p.add_subparsers(dest="team_command", help="Team sub-command")

    team_create = team_sub.add_parser("create", help="Create a new team")
    team_create.add_argument("id", type=str, help="Short unique team ID")
    team_create.add_argument("--name", type=str, default=None, help="Display name (defaults to ID)")
    team_create.add_argument("--desc", type=str, default="", help="Description")

    team_sub.add_parser("list", help="List all teams")

    team_del = team_sub.add_parser("delete", help="Delete a team")
    team_del.add_argument("id", type=str, help="Team ID")

    team_add_member = team_sub.add_parser("add-member", help="Add a user to a team")
    team_add_member.add_argument("team", type=str, help="Team ID")
    team_add_member.add_argument("--user", type=str, required=True, help="User name")
    team_add_member.add_argument("--role", type=str, default="viewer",
                                 choices=["admin", "operator", "viewer"], help="Role in team")

    team_rm_member = team_sub.add_parser("remove-member", help="Remove a user from a team")
    team_rm_member.add_argument("team", type=str, help="Team ID")
    team_rm_member.add_argument("--user", type=str, required=True, help="User name")

    team_add_agent = team_sub.add_parser("add-agent", help="Assign an agent to a team")
    team_add_agent.add_argument("team", type=str, help="Team ID")
    team_add_agent.add_argument("--agent", type=str, required=True, help="Agent name")

    team_rm_agent = team_sub.add_parser("remove-agent", help="Remove an agent from a team")
    team_rm_agent.add_argument("--agent", type=str, required=True, help="Agent name")

    return parser


def cmd_scan() -> None:
    """Run scan: sync configured agents into inventory."""
    configured = get_configured_agents()
    if not configured:
        console.print("[yellow]No agents configured. Create a config file first.[/yellow]")
        console.print("See README.md for configuration instructions.")
        return

    agents = scan_and_report()
    console.print(f"[green]✓[/green] Scan complete. [bold]{len(agents)}[/bold] agent(s) in inventory.")


def cmd_list() -> None:
    """List all agents in inventory."""
    conn = get_connection()
    agents = list_agents(conn)
    conn.close()

    if not agents:
        console.print("[yellow]No agents in inventory. Run 'acp scan' first.[/yellow]")
        return

    table = Table(title="Agent Inventory")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Provider", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("URL")
    table.add_column("Checks")
    table.add_column("Avg RT (ms)", justify="right")
    table.add_column("Tags")

    for a in agents:
        status_style = {
            "online": "green",
            "offline": "red",
            "degraded": "yellow",
            "unknown": "white",
        }.get(a.status.value, "white")
        table.add_row(
            a.name,
            a.provider,
            f"[{status_style}]{a.status.value}[/{status_style}]",
            a.url,
            f"{a.successful_checks}/{a.total_checks}",
            f"{a.avg_response_time_ms:.1f}",
            ", ".join(a.tags),
        )

    console.print(table)


def cmd_health(timeout: float = 5.0) -> None:
    """Run health checks against all configured agents."""
    agents = get_configured_agents()
    if not agents:
        console.print("[yellow]No agents configured. Create a config file first.[/yellow]")
        return

    console.print(f"[bold]Running health checks ({len(agents)} agent(s), timeout={timeout}s)...[/bold]")

    results = run_health_checks(agents, timeout=timeout)

    table = Table(title="Health Check Results")
    table.add_column("Agent", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Response", justify="right")
    table.add_column("Details")

    online_count = 0
    for endpoint, status, elapsed, status_code, error in results:
        status_style = {
            "online": "green",
            "offline": "red",
            "degraded": "yellow",
        }.get(status.value, "white")

        details = ""
        if error:
            details = f"[red]{error}[/red]"
        elif status_code and status_code != 200:
            details = f"HTTP {status_code}"
        elif status == AgentStatus.DEGRADED:
            details = "Degraded response"
        else:
            details = "OK"

        response_str = f"{elapsed:.0f}ms" if elapsed > 0 else "-"

        table.add_row(
            endpoint.name,
            f"[{status_style}]{status.value}[/{status_style}]",
            response_str,
            details,
        )

        if status == AgentStatus.ONLINE:
            online_count += 1

    console.print(table)
    console.print(f"\n[bold]{online_count}/{len(agents)}[/bold] agents online")


def cmd_cost() -> None:
    """Show estimated costs."""
    costs = get_all_costs()
    total = total_monthly_cost()

    if not costs:
        console.print("[yellow]No cost data available. Record costs with 'acp cost-record' or submit token counts via API.[/yellow]")
        return

    table = Table(title="Cost Estimates")
    table.add_column("Agent", style="cyan")
    table.add_column("Month")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Est. Cost", justify="right")

    for c in costs:
        table.add_row(
            c.agent_name,
            c.month,
            f"{c.estimated_tokens_in:,}",
            f"{c.estimated_tokens_out:,}",
            f"${c.estimated_cost_usd:.2f}",
        )

    console.print(table)
    console.print(f"\n[bold]Total estimated monthly cost:[/bold] [green]${total:.2f}[/green]")


def cmd_export(format: str = "json", output: str | None = None) -> None:
    """Export inventory data to file."""
    home = get_home()

    if output:
        out_path = Path(output)
    else:
        filename = f"acp-export.{format}"
        out_path = home / filename

    try:
        if format == "json":
            export_json(out_path)
        else:
            export_csv(out_path)

        console.print(f"[green]✓[/green] Exported to [bold]{out_path}[/bold]")
    except Exception as e:
        console.print(f"[red]✗ Export failed: {e}[/red]")
        sys.exit(1)


def cmd_status() -> None:
    """Show summary statistics."""
    conn = get_connection()
    stats = get_summary_stats(conn)
    conn.close()

    if stats.total_agents == 0:
        console.print("[yellow]No agents in inventory. Run 'acp scan' first.[/yellow]")
        return

    info = Panel(
        f"[bold]Total Agents:[/bold] {stats.total_agents}\n"
        f"  [green]Online:[/green]  {stats.online}\n"
        f"  [red]Offline:[/red]   {stats.offline}\n"
        f"  [yellow]Degraded:[/yellow] {stats.degraded}\n"
        f"  [white]Unknown:[/white]  {stats.unknown}\n\n"
        f"[bold]Total Checks Run:[/bold] {stats.total_checks_run:,}\n"
        f"[bold]Est. Monthly Cost:[/bold] [green]${stats.total_estimated_cost_monthly_usd:.2f}[/green]",
        title="Agent Fleet Status",
    )
    console.print(info)


def cmd_delete(name: str) -> None:
    """Delete an agent from inventory."""
    from agent_control_plane.inventory import delete_agent

    conn = get_connection()
    delete_agent(conn, name)
    conn.close()
    console.print(f"[green]✓[/green] Agent '{name}' deleted.")


def cmd_dashboard(host: str = "127.0.0.1", port: int = 8337) -> None:
    """Start the web UI dashboard."""
    try:
        from agent_control_plane.dashboard import serve_dashboard
        serve_dashboard(host=host, port=port)
    except ImportError as e:
        console.print(f"[red]✗ Dashboard dependencies not installed: {e}[/red]")
        console.print("Run: pip install fastapi uvicorn jinja2")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗ Failed to start dashboard: {e}[/red]")
        sys.exit(1)


def cmd_discover(
    host: str = "127.0.0.1",
    ports: str | None = None,
    register: bool = False,
    timeout: float = 2.0,
) -> None:
    """Auto-discover AI agents on a host."""
    from agent_control_plane.discovery.scanner import probe_endpoint, register_discovered

    if ports:
        port_list = []
        for part in ports.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                port_list.extend(range(int(start), int(end) + 1))
            else:
                port_list.append(int(part))
    else:
        port_list = [11434, 8080, 8000, 5000, 3000, 8337, 9090, 1234]

    console.print(f"[bold]Scanning {host} on {len(port_list)} port(s)...[/bold]")
    found = 0
    for port in port_list:
        result = probe_endpoint(host, port, timeout=timeout)
        if result is not None:
            found += 1
            provider_display = result.get("provider", "unknown")
            name = result["name"]
            console.print(f"  [green]✓[/green] Port {port}: [cyan]{name}[/cyan] ({provider_display})")
            if register:
                record = register_discovered(result)
                console.print(f"    Registered as '{record.name}'")
        else:
            console.print(f"  . Port {port} — no agent detected", style="dim")

    console.print(f"\n[bold]Discovery complete:[/bold] {found} agent(s) found")
    if found > 0 and not register:
        console.print("Run with --register to add discovered agents to inventory")


# ---------------------------------------------------------------------------
# Config Baseline commands
# ---------------------------------------------------------------------------


def cmd_config_baseline(args: argparse.Namespace) -> None:
    """Dispatch config-baseline subcommands."""
    from agent_control_plane.drift import capture_baseline, set_baseline

    if args.config_baseline_command == "capture":
        result = capture_baseline(args.name, timeout=args.timeout)
        if result is None:
            console.print(f"[red]✗[/red] Agent '{args.name}' not found in inventory")
            return
        console.print(f"[green]✓[/green] Baseline captured for [bold]{args.name}[/bold]")
        console.print(f"  Provider: {result.provider}")
        console.print(f"  Version: {result.expected_version or 'unknown'}")

    elif args.config_baseline_command == "set":
        tags = None
        if args.tags:
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        result = set_baseline(
            args.name,
            provider=args.provider,
            health_check_path=args.health_path,
            expected_version=args.version,
            expected_tags=tags,
        )
        if result is None:
            console.print(f"[red]✗[/red] Agent '{args.name}' not found in inventory")
            return
        console.print(f"[green]✓[/green] Baseline set for [bold]{args.name}[/bold]")

    elif args.config_baseline_command == "show":
        from agent_control_plane.inventory import get_config_baseline

        conn = get_connection()
        baseline = get_config_baseline(conn, args.name)
        conn.close()
        if baseline is None:
            console.print(f"[yellow]No baseline for agent '{args.name}'[/yellow]")
            return
        console.print(f"[bold]Baseline: {args.name}[/bold]")
        console.print(f"  Provider:           {baseline.provider}")
        console.print(f"  Health Check Path:  {baseline.health_check_path}")
        console.print(f"  Expected Version:   {baseline.expected_version or 'not set'}")
        console.print(f"  Expected Tags:      {', '.join(baseline.expected_tags) or 'none'}")
        console.print(f"  Additional Fields:  {baseline.additional_fields}")
        console.print(f"  Captured At:        {baseline.captured_at.isoformat()}")
        console.print(f"  Captured By:        {baseline.captured_by}")

    elif args.config_baseline_command == "list":
        from agent_control_plane.inventory import list_config_baselines

        conn = get_connection()
        baselines = list_config_baselines(conn)
        conn.close()
        if not baselines:
            console.print("[yellow]No baselines configured[/yellow]")
            return
        table = Table(title="Configuration Baselines")
        table.add_column("Agent", style="cyan")
        table.add_column("Provider")
        table.add_column("Version")
        table.add_column("Tags")
        table.add_column("Captured")
        for b in baselines:
            table.add_row(
                b.agent_name,
                b.provider,
                b.expected_version or "-",
                ", ".join(b.expected_tags) or "-",
                b.captured_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)

    elif args.config_baseline_command == "delete":
        from agent_control_plane.inventory import delete_config_baseline

        conn = get_connection()
        delete_config_baseline(conn, args.name)
        conn.close()
        console.print(f"[green]✓[/green] Baseline deleted for [bold]{args.name}[/bold]")

    else:
        console.print("[yellow]Unknown config-baseline subcommand[/yellow]")
        console.print("Try: capture, set, show, list, delete")


# ---------------------------------------------------------------------------
# Drift check commands
# ---------------------------------------------------------------------------


def cmd_drift_check(name: str | None = None, timeout: float = 5.0) -> None:
    """Check agents for configuration drift."""
    from agent_control_plane.drift import check_all_drift, check_drift

    if name:
        reports = [check_drift(name, timeout=timeout)]
    else:
        reports = check_all_drift(timeout=timeout)

    if not reports:
        console.print("[yellow]No agents with baselines to check[/yellow]")
        console.print("Run 'acp config-baseline capture <name>' first")
        return

    severity_colors = {
        "none": "white",
        "low": "cyan",
        "medium": "yellow",
        "high": "red",
        "critical": "bold red",
    }

    total_drift = 0
    for report in reports:
        if not report.has_baseline:
            console.print(f"[yellow]No baseline for '{report.agent_name}'[/yellow] - run 'acp config-baseline capture {report.agent_name}'")
            continue

        if report.drift_count == 0:
            console.print(f"[green]✓[/green] [bold]{report.agent_name}[/bold]: no drift detected")
            continue

        total_drift += report.drift_count
        sev = report.max_severity.value if isinstance(report.max_severity, DriftSeverity) else str(report.max_severity)
        color = severity_colors.get(sev, "white")
        console.print(f"[{color}]⚠[/{color}] [bold]{report.agent_name}[/bold]: {report.drift_count} drift(s), max severity: [{color}]{sev}[/{color}]")

        for r in report.results:
            if DriftSeverity(r.severity) == DriftSeverity.NONE:
                continue
            sc = severity_colors.get(r.severity, "white")
            console.print(f"  [{sc}]•[/{sc}] {r.message}")

        console.print("")

    if total_drift > 0:
        console.print(f"\n[bold]{total_drift}[/bold] total drift(s) detected")
    else:
        console.print("\n[green]✓ All agents match their baselines[/green]")


def cmd_drift_report() -> None:
    """Show drift detection history."""
    from agent_control_plane.inventory import get_drift_history, get_drift_summary

    conn = get_connection()
    summary = get_drift_summary(conn)
    records = get_drift_history(conn, limit=50)
    conn.close()

    if not records:
        console.print("[yellow]No drift events recorded[/yellow]")
        return

    # Summary
    console.print("[bold]Drift Summary[/bold]")
    for sev in ("critical", "high", "medium", "low", "none"):
        count = summary.get(sev, 0)
        if count > 0:
            console.print(f"  {sev}: {count}")
    console.print("")

    # Recent events
    table = Table(title="Recent Drift Events")
    table.add_column("Time", style="dim")
    table.add_column("Agent", style="cyan")
    table.add_column("Field")
    table.add_column("Expected")
    table.add_column("Actual")
    table.add_column("Severity")

    severity_colors = {
        "none": "white",
        "low": "cyan",
        "medium": "yellow",
        "high": "red",
        "critical": "bold red",
    }

    for r in records:
        color = severity_colors.get(r.severity, "white")
        table.add_row(
            r.detected_at.strftime("%m-%d %H:%M"),
            r.agent_name,
            r.field_name,
            r.expected[:40] if r.expected else "-",
            r.actual[:40] if r.actual else "-",
            f"[{color}]{r.severity}[/{color}]",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------


def cmd_user(args: argparse.Namespace) -> None:
    """Dispatch user subcommands."""
    from agent_control_plane.auth import create_user_with_key
    from agent_control_plane.inventory import delete_user, list_users

    if args.user_command == "create":
        user, api_key = create_user_with_key(
            name=args.name,
            email=args.email,
            role=args.role,
        )
        console.print(f"[green]✓[/green] User [bold]{user.name}[/bold] created ([cyan]{user.role.value}[/cyan])")
        console.print(f"\n  API Key: [bold yellow]{api_key}[/bold yellow]")
        console.print("  [dim]Save this key — it will not be shown again.[/dim]")

    elif args.user_command == "list":
        conn = get_connection()
        users = list_users(conn)
        conn.close()
        if not users:
            console.print("[yellow]No users configured. Single-user mode active.[/yellow]")
            return
        table = Table(title="Users")
        table.add_column("Name", style="cyan")
        table.add_column("Email")
        table.add_column("Role")
        table.add_column("Created")
        for u in users:
            table.add_row(u.name, u.email, u.role.value,
                          u.created_at.strftime("%Y-%m-%d"))
        console.print(table)

    elif args.user_command == "delete":
        conn = get_connection()
        delete_user(conn, args.name)
        conn.close()
        console.print(f"[green]✓[/green] User [bold]{args.name}[/bold] deleted")

    else:
        console.print("[yellow]Unknown user subcommand[/yellow]")


# ---------------------------------------------------------------------------
# Team commands
# ---------------------------------------------------------------------------


def cmd_team(args: argparse.Namespace) -> None:
    """Dispatch team subcommands."""
    from agent_control_plane.inventory import (
        add_team_member,
        assign_agent_to_team,
        delete_team,
        list_team_members,
        list_teams,
        remove_team_member,
        unassign_agent_from_team,
        upsert_team,
    )
    from agent_control_plane.models import Team, TeamMember

    if args.team_command == "create":
        team_id = args.id
        team_name = args.name if args.name else args.id
        now = datetime.now(timezone.utc)
        team = Team(id=team_id, name=team_name, description=args.desc, created_at=now)
        conn = get_connection()
        upsert_team(conn, team)
        conn.close()
        console.print(f"[green]✓[/green] Team [bold]{team_name}[/bold] created (ID: {team_id})")

    elif args.team_command == "list":
        conn = get_connection()
        teams = list_teams(conn)
        conn.close()
        if not teams:
            console.print("[yellow]No teams created yet[/yellow]")
            return
        table = Table(title="Teams")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Description")
        table.add_column("Members", justify="right")
        for t in teams:
            conn2 = get_connection()
            members = list_team_members(conn2, t.id)
            conn2.close()
            table.add_row(t.id, t.name, t.description, str(len(members)))
        console.print(table)

    elif args.team_command == "delete":
        conn = get_connection()
        delete_team(conn, args.id)
        conn.close()
        console.print(f"[green]✓[/green] Team [bold]{args.id}[/bold] deleted")

    elif args.team_command == "add-member":
        member = TeamMember(
            user_name=args.user,
            team_id=args.team,
            role_in_team=args.role,
        )
        conn = get_connection()
        add_team_member(conn, member)
        conn.close()
        console.print(f"[green]✓[/green] User [bold]{args.user}[/bold] added to team [bold]{args.team}[/bold] as {args.role}")

    elif args.team_command == "remove-member":
        conn = get_connection()
        remove_team_member(conn, args.user, args.team)
        conn.close()
        console.print(f"[green]✓[/green] User [bold]{args.user}[/bold] removed from team [bold]{args.team}[/bold]")

    elif args.team_command == "add-agent":
        conn = get_connection()
        assign_agent_to_team(conn, args.agent, args.team)
        conn.close()
        console.print(f"[green]✓[/green] Agent [bold]{args.agent}[/bold] assigned to team [bold]{args.team}[/bold]")

    elif args.team_command == "remove-agent":
        conn = get_connection()
        unassign_agent_from_team(conn, args.agent)
        conn.close()
        console.print(f"[green]✓[/green] Agent [bold]{args.agent}[/bold] unassigned from team")

    else:
        console.print("[yellow]Unknown team subcommand[/yellow]")


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "scan":
            cmd_scan()
        elif args.command == "list":
            cmd_list()
        elif args.command == "health":
            cmd_health(timeout=args.timeout)
        elif args.command == "cost":
            cmd_cost()
        elif args.command == "export":
            cmd_export(format=args.format, output=args.output)
        elif args.command == "status":
            cmd_status()
        elif args.command == "delete":
            cmd_delete(args.name)
        elif args.command == "dashboard":
            cmd_dashboard(host=args.host, port=args.port)
        elif args.command == "discover":
            cmd_discover(
                host=args.host, ports=args.ports,
                register=args.register, timeout=args.timeout,
            )
        elif args.command == "config-baseline":
            cmd_config_baseline(args)
        elif args.command == "drift-check":
            cmd_drift_check(name=args.name, timeout=args.timeout)
        elif args.command == "drift-report":
            cmd_drift_report()
        elif args.command == "user":
            cmd_user(args)
        elif args.command == "team":
            cmd_team(args)
        else:
            parser.print_help()
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        return 1
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {e}[/red]")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
