"""Command-line interface for the WordPress Scraping Agent."""

import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

from src.agent.orchestrator import ScrapingAgent
from src.agent.registry import registry
from src.agent.state import StateManager
from src.config import PipelineConfig

console = Console()


def cmd_run(args: argparse.Namespace) -> None:
    """Execute scraping pipeline."""
    config = PipelineConfig()
    if args.source_url:
        config.source_url = args.source_url
    if args.workspace:
        config.workspace_dir = Path(args.workspace)
    if args.output:
        config.output_dir = Path(args.output)

    agent = ScrapingAgent(config=config)
    success = agent.execute_pipeline(resume=False, force_refresh=args.force_refresh)
    sys.exit(0 if success else 1)


def cmd_resume(args: argparse.Namespace) -> None:
    """Resume scraping pipeline from last checkpoint."""
    config = PipelineConfig()
    if args.workspace:
        config.workspace_dir = Path(args.workspace)
    if args.output:
        config.output_dir = Path(args.output)

    agent = ScrapingAgent(config=config)
    success = agent.execute_pipeline(resume=True, force_refresh=False)
    sys.exit(0 if success else 1)


def cmd_status(args: argparse.Namespace) -> None:
    """Display current pipeline execution state."""
    config = PipelineConfig()
    if args.workspace:
        config.workspace_dir = Path(args.workspace)

    state_mgr = StateManager(config.state_file)
    state = state_mgr.load()

    if not state:
        console.print("[yellow]No active pipeline execution state found.[/yellow]")
        return

    table = Table(title="WordPress Scraping Pipeline Status", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="cyan", width=25)
    table.add_column("Value", style="green")

    table.add_row("Run ID", state.run_id)
    table.add_row("Source URL", state.source or config.source_url)
    table.add_row("Current Phase", state.phase.value)
    table.add_row("Created At", state.created_at)
    table.add_row("Updated At", state.updated_at)
    table.add_row("Completed Tools", ", ".join(state.completed_tools) or "None")
    table.add_row("Errors Logged", str(len(state.errors)))

    console.print(table)

    if state.statistics:
        stats_table = Table(title="Pipeline Statistics", show_header=True, header_style="bold blue")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Count", justify="right", style="bold green")
        for k, v in state.statistics.items():
            stats_table.add_row(k.replace("_", " ").title(), str(v))
        console.print(stats_table)


def cmd_tools(args: argparse.Namespace) -> None:
    """List all registered tools in the ToolRegistry."""
    table = Table(title="Registered Scraping Tools", show_header=True, header_style="bold cyan")
    table.add_column("Tool Name", style="bold white")
    table.add_column("Version", justify="center", style="yellow")
    table.add_column("Status", justify="center", style="green")
    table.add_column("Capabilities", style="blue")
    table.add_column("Description", style="dim")

    for meta in sorted(registry.list_tools(), key=lambda m: m.name):
        table.add_row(
            meta.name,
            f"v{meta.version}",
            meta.status.value.upper(),
            ", ".join(meta.capabilities),
            meta.description,
        )

    console.print(table)


def cmd_validate(args: argparse.Namespace) -> None:
    """Run export validation checklist on current output directory."""
    config = PipelineConfig()
    if args.output:
        config.output_dir = Path(args.output)
    if args.workspace:
        config.workspace_dir = Path(args.workspace)

    agent = ScrapingAgent(config=config)
    res = agent._run_tool("validate_export")
    if res.success and res.data.get("all_passed"):
        console.print("[bold green]Validation PASSED: Output structure is complete and valid.[/bold green]")
        sys.exit(0)
    else:
        console.print("[bold red]Validation FAILED: Checklist items failed.[/bold red]")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="WordPress Scraping Agent Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    p_run = subparsers.add_parser("run", help="Run full pipeline")
    p_run.add_argument("--source-url", help="Target WordPress website URL")
    p_run.add_argument("--workspace", help="Path to workspace directory")
    p_run.add_argument("--output", help="Path to output delivery directory")
    p_run.add_argument("--force-refresh", action="store_true", help="Force fresh scrape instead of reusing raw cache")
    p_run.set_defaults(func=cmd_run)

    # resume command
    p_resume = subparsers.add_parser("resume", help="Resume pipeline from checkpoint")
    p_resume.add_argument("--workspace", help="Path to workspace directory")
    p_resume.add_argument("--output", help="Path to output delivery directory")
    p_resume.set_defaults(func=cmd_resume)

    # status command
    p_status = subparsers.add_parser("status", help="Show current execution status")
    p_status.add_argument("--workspace", help="Path to workspace directory")
    p_status.set_defaults(func=cmd_status)

    # tools command
    p_tools = subparsers.add_parser("tools", help="List registered tools")
    p_tools.set_defaults(func=cmd_tools)

    # validate command
    p_validate = subparsers.add_parser("validate", help="Validate output delivery package")
    p_validate.add_argument("--output", help="Path to output delivery directory")
    p_validate.add_argument("--workspace", help="Path to workspace directory")
    p_validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
