"""CLI interface for the Agent Control Plane."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from agent_control_plane import __version__
from agent_control_plane.config import get_home
from agent_control_plane.discovery import scan_and_report
from agent_control_plane.exporter import export_csv, export_json
from agent_control_plane.health import check_agent_health, run_health_checks
from agent_control_plane.cost_tracker import get_all_costs, total_monthly_cost
from agent_control_plane.inventory import get_connection, get_summary_stats, list_agents
from agent_control_plane.discovery import get_configured_agents
from agent_control_plane.models import AgentStatus


console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-control-plane",
        description="AI Agent Operations Platform — discover, inventory, monitor, and track costs for AI agents.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
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

    # delete
    delete_p = sub.add_parser("delete", help="Remove an agent from inventory")
    delete_p.add_argument("name", type=str, help="Agent name to delete")

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
