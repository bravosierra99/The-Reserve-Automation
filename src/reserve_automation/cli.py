"""CLI interface for The Reserve Automation."""

import asyncio
import json
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .core.config import Config
from .core.exceptions import ConfigurationError, ReserveAutomationError
from .pipeline import extraction_pipeline
from .utils.logging import logger, setup_logging

console = Console()

# Usage: logger.info("message"), logger.debug("message"), logger.error("message"), etc.


@click.group()
@click.option("--config", type=Path, help="Config file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging (DEBUG level)")
@click.pass_context
def cli(ctx, config, verbose):
    """
    The Reserve Automation - Bottle ingestion pipeline.

    Automate bottle metadata extraction from PDFs, images, and other sources.
    Generate Obsidian-compatible markdown files for The Reserve vault.
    """
    ctx.ensure_object(dict)

    try:
        # Load configuration
        ctx.obj["config"] = Config.load(config)

        # Setup logging
        setup_logging(ctx.obj["config"].model_dump(), verbose)
        logger.debug("Reserve Automation initialized")

    except ConfigurationError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        console.print("\n[yellow]Hint:[/yellow] Run 'reserve-automation config init' to create user config")
        ctx.exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        ctx.exit(1)


@cli.command()
@click.argument("input_file", type=Path)
@click.option("--type", type=click.Choice(["pdf", "image", "auto"]), default="auto")
@click.option("--beverage", type=click.Choice(["wine", "whiskey", "auto"]), default="auto")
@click.option("--output", "-o", type=Path, help="Output JSON file")
@click.option("--review/--no-review", default=True, help="Interactive review")
@click.pass_context
def extract(ctx, input_file, type, beverage, output, review):
    """
    Extract bottle data from PDF or image.

    INPUT_FILE: Path to PDF, image, or screenshot to process

    \b
    Examples:
        reserve-automation extract sommelier_list.pdf
        reserve-automation extract label.jpg --type image --beverage whiskey
        reserve-automation extract scan.pdf --output bottles.json --no-review
    """
    # Validate input file
    if not input_file.exists():
        console.print(f"[red]Error:[/red] File not found: {input_file}")
        ctx.exit(1)

    config = ctx.obj.get("config")
    if not config:
        console.print("[red]Error:[/red] Configuration not loaded")
        ctx.exit(1)

    # Run extraction pipeline
    console.print(f"\n[bold]Extracting from:[/bold] {input_file.name}")
    console.print(f"[dim]Input type: {type} | Beverage: {beverage}[/dim]\n")

    try:
        with console.status("[bold green]Processing...", spinner="dots"):
            result = asyncio.run(
                extraction_pipeline(
                    input_file=input_file,
                    config=config.model_dump(),
                    input_type=type,
                    beverage_type=beverage,
                )
            )

        # Display results
        _display_extraction_results(result, review)

        # Save to JSON if requested
        if output:
            _save_extraction_json(result, output)
            console.print(f"\n[green]✓ Saved to:[/green] {output}")

        # Exit code based on results
        if result.errors:
            ctx.exit(1)

    except Exception as e:
        console.print(f"\n[red]Extraction failed:[/red] {e}")
        logger.exception("Extraction error")
        ctx.exit(1)


@cli.command()
@click.argument("extraction_json", type=Path)
@click.option("--vault", type=Path, help="Vault path (overrides config)")
@click.option("--branch", default="tastings-backup", help="Git branch")
@click.option("--commit/--no-commit", default=False, help="Auto-commit to git")
@click.option("--dry-run", is_flag=True, help="Show what would be created")
@click.pass_context
def generate(ctx, extraction_json, vault, branch, commit, dry_run):
    """
    Generate Obsidian files from extraction results.

    EXTRACTION_JSON: Path to extraction result JSON file

    \b
    Examples:
        reserve-automation generate bottles.json --commit
        reserve-automation generate bottles.json --dry-run
    """
    console.print("[yellow]Generate command not yet implemented[/yellow]")
    console.print(f"Would generate from: {extraction_json}")
    # TODO: Implement generation


@cli.command()
@click.argument("input_file", type=Path)
@click.option("--output-dir", type=Path, help="Output directory for results")
@click.option("--commit/--no-commit", default=False, help="Auto-commit to git")
@click.pass_context
def pipeline(ctx, input_file, output_dir, commit):
    """
    Run full pipeline: extract → generate → commit.

    INPUT_FILE: Path to PDF, image, or screenshot to process

    This is a convenience command that combines:
      1. extract (with review)
      2. generate
      3. git commit (if --commit)

    \b
    Example:
        reserve-automation pipeline sommelier_list.pdf --commit
    """
    console.print("[yellow]Pipeline command not yet implemented[/yellow]")
    console.print(f"Would run pipeline on: {input_file}")
    # TODO: Implement full pipeline


# Config management commands
@cli.group(name="config")
def config_group():
    """Configuration management commands."""
    pass


@config_group.command("show")
@click.pass_context
def config_show(ctx):
    """Show current configuration."""
    config = ctx.obj.get("config")
    if config:
        console.print(config.model_dump_json(indent=2))
    else:
        console.print("[red]Configuration not loaded[/red]")


@config_group.command("init")
def config_init():
    """Initialize user configuration file."""
    import shutil

    user_config = Path("config/user.yaml")
    example_config = Path("config/user.yaml.example")

    if user_config.exists():
        console.print("[yellow]config/user.yaml already exists[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    if not example_config.exists():
        console.print("[red]Error: config/user.yaml.example not found[/red]")
        return

    # Copy example to user.yaml
    shutil.copy(example_config, user_config)

    console.print("[green]✓ Created config/user.yaml[/green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("1. Edit config/user.yaml")
    console.print("2. Set paths.vault to your the-reserve directory")
    console.print("3. Update LLM base_url if LM Studio is on another machine")


@config_group.command("validate")
@click.pass_context
def config_validate(ctx):
    """Validate configuration files."""
    try:
        config = Config.load()
        console.print("[green]✓ Configuration is valid[/green]")

        # Check vault path
        if not config.vault_path:
            console.print("[yellow]⚠ Warning: vault path not set[/yellow]")
        elif not config.vault_path.exists():
            console.print(f"[red]✗ Vault path does not exist: {config.vault_path}[/red]")
        else:
            console.print(f"[green]✓ Vault path OK: {config.vault_path}[/green]")

    except ConfigurationError as e:
        console.print(f"[red]✗ Configuration invalid:[/red] {e}")
        ctx.exit(1)


# LLM diagnostic commands
@cli.group()
def llm():
    """LLM diagnostics and testing."""
    pass


@llm.command("test")
@click.option("--provider", help="Provider name to test (tests all if not specified)")
@click.pass_context
def llm_test(ctx, provider):
    """Test LLM provider connections."""
    console.print("[yellow]LLM test command not yet implemented[/yellow]")
    # TODO: Implement LLM health checks


@llm.command("list")
@click.pass_context
def llm_list(ctx):
    """List configured LLM providers."""
    config = ctx.obj.get("config")
    if not config:
        console.print("[red]Configuration not loaded[/red]")
        return

    llm_config = config.llm
    providers = llm_config.get("providers", {})

    console.print(f"\n[bold]Configured LLM Providers:[/bold] ({len(providers)})\n")

    for name, prov_config in providers.items():
        provider_type = prov_config.get("provider", "unknown")
        model = prov_config.get("model", "N/A")
        base_url = prov_config.get("base_url", "N/A")

        console.print(f"[cyan]{name}[/cyan]")
        console.print(f"  Type: {provider_type}")
        console.print(f"  Model: {model}")
        if base_url != "N/A":
            console.print(f"  URL: {base_url}")
        console.print()


def _display_extraction_results(result, show_review=True):
    """Display extraction results in a nice format."""
    # Summary panel
    summary = f"""[bold]Extraction Complete[/bold]

Source: {result.source_type}
Bottles extracted: {result.total_extracted}
High confidence: [green]{result.high_confidence_count}[/green]
Needs review: [yellow]{result.needs_review_count}[/yellow]
Processing time: {result.processing_time_seconds:.2f}s"""

    if result.total_tokens_used > 0:
        summary += f"\nTokens used: {result.total_tokens_used:,}"
    if result.total_cost > 0:
        summary += f"\nEstimated cost: ${result.total_cost:.4f}"

    console.print(Panel(summary, border_style="green"))

    # Show errors/warnings
    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for error in result.errors:
            console.print(f"  • {error}")

    if result.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warning in result.warnings:
            console.print(f"  • {warning}")

    # High confidence bottles table
    if result.high_confidence:
        console.print("\n[bold green]✓ High Confidence Bottles[/bold green]")
        table = Table(show_header=True, header_style="bold green")
        table.add_column("Producer", style="cyan")
        table.add_column("Name")
        table.add_column("Year", justify="right")
        table.add_column("Type")
        table.add_column("Confidence", justify="right")

        for bottle in result.high_confidence:
            table.add_row(
                bottle.producer,
                bottle.name,
                str(bottle.year) if bottle.year else "-",
                bottle.beverage_type or bottle.type,
                f"{bottle.confidence:.2f}",
            )

        console.print(table)

    # Needs review bottles table
    if result.needs_review and show_review:
        console.print("\n[bold yellow]⚠ Needs Review[/bold yellow]")
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Producer", style="cyan")
        table.add_column("Name")
        table.add_column("Year", justify="right")
        table.add_column("Type")
        table.add_column("Confidence", justify="right")
        table.add_column("Issues", style="dim")

        for bottle in result.needs_review:
            # Identify missing fields
            issues = []
            if not bottle.year:
                issues.append("no year")
            if not bottle.beverage_type and not bottle.variety:
                issues.append("no type")
            if not bottle.region and not bottle.country:
                issues.append("no location")
            if bottle.price is None:
                issues.append("no price")

            table.add_row(
                bottle.producer,
                bottle.name,
                str(bottle.year) if bottle.year else "-",
                bottle.beverage_type or bottle.type,
                f"{bottle.confidence:.2f}",
                ", ".join(issues) if issues else "-",
            )

        console.print(table)


def _save_extraction_json(result, output_path: Path):
    """Save extraction result to JSON file."""
    output_data = {
        "metadata": {
            "source_file": result.source_file,
            "source_type": result.source_type,
            "total_extracted": result.total_extracted,
            "high_confidence_count": result.high_confidence_count,
            "needs_review_count": result.needs_review_count,
            "processing_time_seconds": result.processing_time_seconds,
            "total_tokens_used": result.total_tokens_used,
            "total_cost": result.total_cost,
        },
        "bottles": [bottle.model_dump() for bottle in result.bottles],
        "high_confidence": [bottle.model_dump() for bottle in result.high_confidence],
        "needs_review": [bottle.model_dump() for bottle in result.needs_review],
        "errors": result.errors,
        "warnings": result.warnings,
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2, default=str)


def main():
    """Main entry point."""
    try:
        cli()
    except ReserveAutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    main()
