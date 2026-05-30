"""CLI interface for The Reserve Automation."""

import asyncio
import json
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .core.config import Config
from .core.exceptions import ConfigurationError, ReserveAutomationError, GenerationError
from .core.models import BottleMetadata
from .enrichment import MetadataEnricher
from .extractors.tasting_extractor import TastingExtractor
from .extractors.image_extractor import ImageMetadataExtractor
from .generators import ObsidianGenerator
from .generators.tasting_generator import TastingGenerator
from .llm import LLMGateway
from .pipeline import extraction_pipeline
from .utils.bottle_matcher import BottleMatcher
from .utils.image_search import BottleLabelSearcher
from .utils.label_processor import LabelImageProcessor
from .utils.llm_label_finder import LLMLabelFinder
from .utils.logging import logger, setup_logging
from .utils.obsidian_updater import ObsidianUpdater
from .utils.vault_reader import VaultReader

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
    config = ctx.obj["config"]

    try:
        # Validate extraction JSON exists
        if not extraction_json.exists():
            console.print(f"[red]Error:[/red] File not found: {extraction_json}")
            ctx.exit(1)

        # Load extraction results
        console.print(f"Loading extraction results from: {extraction_json}")
        with open(extraction_json) as f:
            extraction_data = json.load(f)

        # Parse bottles
        bottles_data = extraction_data.get("bottles", [])
        if not bottles_data:
            console.print("[yellow]No bottles found in extraction results[/yellow]")
            ctx.exit(0)

        bottles = [BottleMetadata(**b) for b in bottles_data]
        console.print(f"Found {len(bottles)} bottles to process")

        # Determine vault path
        vault_path = vault or config.vault_path
        if not vault_path:
            console.print("[red]Error:[/red] Vault path not specified. Use --vault or set in config.")
            ctx.exit(1)

        # Determine template directory
        template_dir = Path("templates")  # Relative to project root
        if not template_dir.exists():
            console.print(f"[red]Error:[/red] Template directory not found: {template_dir}")
            ctx.exit(1)

        # Initialize generator
        console.print(f"Vault path: {vault_path}")
        if dry_run:
            console.print("[yellow]DRY RUN MODE - No files will be created[/yellow]")

        generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

        # Generate files
        with console.status("[bold green]Generating Obsidian files..."):
            generated = generator.generate_batch(bottles, dry_run=dry_run)

        # Display results
        console.print("\n")
        console.print(Panel(
            f"[green]Generated {len(generated)} files[/green]\n"
            f"Vault: {vault_path}",
            title="Generation Complete"
        ))

        # Show generated files
        if generated:
            table = Table(title="Generated Files")
            table.add_column("Producer", style="cyan")
            table.add_column("Name", style="magenta")
            table.add_column("Year", style="yellow")
            table.add_column("Path", style="dim")

            for file in generated:
                table.add_row(
                    file.bottle.producer,
                    file.bottle.name,
                    str(file.bottle.year) if file.bottle.year else "NV",
                    str(file.file_path.relative_to(vault_path))
                )

            console.print(table)

        # Git commit (if requested and not dry run)
        if commit and not dry_run:
            console.print("\n[yellow]Git commit not yet implemented[/yellow]")
            # TODO: Implement git commit

    except GenerationError as e:
        console.print(f"[red]Generation error:[/red] {e}")
        ctx.exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        logger.exception("Generate command failed")
        ctx.exit(1)


@cli.command(name="enrich-vault")
@click.option("--beverage", type=click.Choice(["wine", "whiskey", "all"]), default="all", help="Filter by beverage type")
@click.option("--fields", multiple=True, help="Specific fields to enrich (default: all missing)")
@click.option("--dry-run", is_flag=True, help="Show what would be enriched without making changes")
@click.pass_context
def enrich_vault(ctx, beverage, fields, dry_run):
    """
    Enrich bottles already in your Obsidian vault.

    Reads existing bottle files from the vault, enriches missing metadata
    using LLM knowledge, and regenerates the files with enriched data.

    Only fills in missing (null/empty) fields - never overwrites existing data.

    \b
    Examples:
        reserve-automation enrich-vault                    # Enrich all bottles
        reserve-automation enrich-vault --beverage wine    # Only wines
        reserve-automation enrich-vault --fields country region  # Specific fields
        reserve-automation enrich-vault --dry-run          # Preview changes
    """
    config = ctx.obj["config"]

    try:
        vault_path = config.vault_path
        if not vault_path:
            console.print("[red]Error:[/red] Vault path not configured")
            ctx.exit(1)

        # Read bottles from vault
        console.print(f"Reading bottles from vault: {vault_path}")
        reader = VaultReader(vault_path)

        beverage_filter = None if beverage == "all" else beverage
        bottles = reader.read_all_bottles(beverage_type=beverage_filter)

        if not bottles:
            console.print("[yellow]No bottles found in vault[/yellow]")
            ctx.exit(0)

        console.print(f"Found {len(bottles)} bottles\n")

        # Initialize LLM and enricher
        llm_config = config.llm
        llm_gateway = LLMGateway(llm_config)
        enricher = MetadataEnricher(llm_gateway)

        # Convert fields tuple to list
        fields_list = list(fields) if fields else None
        if fields_list:
            console.print(f"[dim]Enriching only: {', '.join(fields_list)}[/dim]\n")

        if dry_run:
            console.print("[yellow]DRY RUN MODE - No files will be modified[/yellow]\n")

        # Run enrichment
        with console.status("[bold green]Enriching metadata..."):
            enriched_bottles, summary = asyncio.run(
                enricher.enrich_batch(bottles, fields=fields_list)
            )

        # Display results
        console.print("\n")
        console.print(Panel(
            f"[green]Enriched {summary['enriched']} bottles[/green]\n"
            f"Fields added: {summary['total_fields_added']}\n"
            f"Tokens used: {summary['total_tokens']:,}\n"
            f"Skipped: {summary['skipped']} (no missing fields)\n"
            f"Errors: {summary['errors']}",
            title="Enrichment Complete"
        ))

        # Show enriched bottles
        if summary['enriched'] > 0:
            table = Table(title="Enriched Bottles")
            table.add_column("Producer", style="cyan")
            table.add_column("Name", style="magenta")
            table.add_column("Type", style="yellow")
            table.add_column("Added Fields", style="green")

            for original, enriched in zip(bottles, enriched_bottles):
                if enriched.enriched:
                    added = []
                    if original.country != enriched.country:
                        added.append("country")
                    if original.region != enriched.region:
                        added.append("region")
                    if original.variety != enriched.variety:
                        added.append("variety")
                    if original.vineyard != enriched.vineyard:
                        added.append("vineyard")
                    if original.mash_bill != enriched.mash_bill:
                        added.append("mash_bill")
                    if original.barrel_type != enriched.barrel_type:
                        added.append("barrel_type")

                    if added:
                        table.add_row(
                            enriched.producer,
                            enriched.name,
                            enriched.type,
                            ", ".join(added)
                        )

            console.print(table)

        # Regenerate vault files (unless dry run)
        if not dry_run and summary['enriched'] > 0:
            console.print("\n[bold]Regenerating vault files...[/bold]")

            template_dir = Path("templates")
            generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

            with console.status("[bold green]Regenerating files..."):
                generated = generator.generate_batch(enriched_bottles, dry_run=False)

            console.print(f"[green]✓ Regenerated {len(generated)} files[/green]")

    except Exception as e:
        console.print(f"[red]Vault enrichment failed:[/red] {e}")
        logger.exception("Enrich vault command failed")
        ctx.exit(1)


@cli.command(name="verify-metadata")
@click.option("--beverage", type=click.Choice(["wine", "whiskey", "all"]), default="all", help="Filter by beverage type")
@click.option("--limit", type=int, help="Test on first N bottles (default: all)")
@click.option("--dry-run", is_flag=True, help="Show what would change without modifying files")
@click.pass_context
def verify_metadata(ctx, beverage, limit, dry_run):
    """
    Verify and correct ALL bottle metadata using web search.

    Unlike enrich-vault which only fills missing fields, this command
    verifies existing data and corrects any inaccuracies found via web search.

    Trusts that producer name and vintage are correct.
    Verifies and corrects: country, region, variety, vineyard/estate.

    \b
    Examples:
        reserve-automation verify-metadata --limit 2 --dry-run  # Test on 2 bottles
        reserve-automation verify-metadata --beverage wine       # Verify all wines
        reserve-automation verify-metadata                       # Verify everything
    """
    config = ctx.obj["config"]

    try:
        vault_path = config.vault_path
        if not vault_path:
            console.print("[red]Error:[/red] Vault path not configured")
            ctx.exit(1)

        # Read bottles from vault
        console.print(f"Reading bottles from vault: {vault_path}")
        reader = VaultReader(vault_path)

        beverage_filter = None if beverage == "all" else beverage
        bottles = reader.read_all_bottles(beverage_type=beverage_filter)

        if not bottles:
            console.print("[yellow]No bottles found in vault[/yellow]")
            ctx.exit(0)

        # Apply limit if specified
        if limit:
            bottles = bottles[:limit]
            console.print(f"Testing on first {limit} bottles\n")
        else:
            console.print(f"Found {len(bottles)} bottles\n")

        # Initialize LLM and enricher
        llm_config = config.llm
        llm_gateway = LLMGateway(llm_config)
        enricher = MetadataEnricher(llm_gateway)

        if dry_run:
            console.print("[yellow]DRY RUN MODE - No files will be modified[/yellow]\n")

        # Run verification
        with console.status("[bold green]Verifying metadata..."):
            verified_bottles, summary = asyncio.run(
                enricher.verify_batch(bottles)
            )

        # Display results
        console.print("\n")
        console.print(Panel(
            f"[green]Verified {summary['verified']} bottles[/green]\n"
            f"Corrections made: {summary['total_corrections']}\n"
            f"Tokens used: {summary['total_tokens']:,}\n"
            f"Errors: {summary['errors']}",
            title="Verification Complete"
        ))

        # Show corrected bottles
        if summary['total_corrections'] > 0:
            table = Table(title="Corrected Metadata")
            table.add_column("Producer", style="cyan")
            table.add_column("Name", style="magenta")
            table.add_column("Field", style="yellow")
            table.add_column("Old Value", style="red")
            table.add_column("New Value", style="green")

            for original, verified in zip(bottles, verified_bottles):
                # Check for changes
                changes = {}
                if original.country != verified.country:
                    changes["country"] = (original.country, verified.country)
                if original.region != verified.region:
                    changes["region"] = (original.region, verified.region)
                if original.variety != verified.variety:
                    changes["variety"] = (original.variety, verified.variety)
                if original.vineyard != verified.vineyard:
                    changes["vineyard"] = (original.vineyard, verified.vineyard)
                if original.mash_bill != verified.mash_bill:
                    changes["mash_bill"] = (original.mash_bill, verified.mash_bill)
                if original.barrel_type != verified.barrel_type:
                    changes["barrel_type"] = (original.barrel_type, verified.barrel_type)

                for field, (old_val, new_val) in changes.items():
                    table.add_row(
                        verified.producer,
                        verified.name,
                        field,
                        str(old_val) if old_val else "(empty)",
                        str(new_val)
                    )

            console.print(table)
        else:
            console.print("\n[green]✓ All metadata verified correct - no corrections needed[/green]")

        # Regenerate vault files (unless dry run)
        if not dry_run and summary['total_corrections'] > 0:
            console.print("\n[bold]Regenerating vault files with corrected metadata...[/bold]")

            template_dir = Path("templates")
            generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

            with console.status("[bold green]Regenerating files..."):
                generated = generator.generate_batch(verified_bottles, dry_run=False)

            console.print(f"[green]✓ Regenerated {len(generated)} files[/green]")

    except Exception as e:
        console.print(f"[red]Metadata verification failed:[/red] {e}")
        logger.exception("Verify metadata command failed")
        ctx.exit(1)


@cli.command()
@click.argument("extraction_json", type=Path)
@click.option("--fields", multiple=True, help="Specific fields to enrich (default: all missing)")
@click.option("--output", "-o", type=Path, help="Output JSON file (default: overwrite input)")
@click.option("--regenerate/--no-regenerate", default=False, help="Regenerate Obsidian files after enrichment")
@click.pass_context
def lookup(ctx, extraction_json, fields, output, regenerate):
    """
    Lookup missing metadata using LLM knowledge.

    EXTRACTION_JSON: Path to extraction result JSON file

    Uses LLM to fill in missing metadata (country, region, variety, etc.)
    based on producer name, wine name, and context clues.

    \b
    Examples:
        reserve-automation lookup bottles.json
        reserve-automation lookup bottles.json --fields country region
        reserve-automation lookup bottles.json --output enriched.json --regenerate
    """
    config = ctx.obj["config"]

    try:
        # Validate extraction JSON exists
        if not extraction_json.exists():
            console.print(f"[red]Error:[/red] File not found: {extraction_json}")
            ctx.exit(1)

        # Load extraction results
        console.print(f"Loading bottles from: {extraction_json}")
        with open(extraction_json) as f:
            extraction_data = json.load(f)

        # Parse bottles
        bottles_data = extraction_data.get("bottles", [])
        if not bottles_data:
            console.print("[yellow]No bottles found in extraction results[/yellow]")
            ctx.exit(0)

        bottles = [BottleMetadata(**b) for b in bottles_data]
        console.print(f"Found {len(bottles)} bottles\n")

        # Initialize LLM gateway and enricher
        llm_config = config.llm
        llm_gateway = LLMGateway(llm_config)
        enricher = MetadataEnricher(llm_gateway)

        # Convert fields tuple to list (or None)
        fields_list = list(fields) if fields else None
        if fields_list:
            console.print(f"[dim]Enriching only: {', '.join(fields_list)}[/dim]\n")

        # Run enrichment
        with console.status("[bold green]Enriching metadata..."):
            enriched_bottles, summary = asyncio.run(
                enricher.enrich_batch(bottles, fields=fields_list)
            )

        # Display results
        console.print("\n")
        console.print(Panel(
            f"[green]Enriched {summary['enriched']} bottles[/green]\n"
            f"Fields added: {summary['total_fields_added']}\n"
            f"Tokens used: {summary['total_tokens']:,}\n"
            f"Skipped: {summary['skipped']} (no missing fields)\n"
            f"Errors: {summary['errors']}",
            title="Enrichment Complete"
        ))

        # Show enriched bottles
        if summary['enriched'] > 0:
            table = Table(title="Enriched Bottles")
            table.add_column("Producer", style="cyan")
            table.add_column("Name", style="magenta")
            table.add_column("Added Fields", style="green")

            for original, enriched in zip(bottles, enriched_bottles):
                if enriched.enriched:
                    added = []
                    if original.country != enriched.country:
                        added.append("country")
                    if original.region != enriched.region:
                        added.append("region")
                    if original.variety != enriched.variety:
                        added.append("variety")

                    if added:
                        table.add_row(
                            enriched.producer,
                            enriched.name,
                            ", ".join(added)
                        )

            console.print(table)

        # Save enriched data
        output_path = output or extraction_json
        extraction_data["bottles"] = [b.model_dump() for b in enriched_bottles]

        with open(output_path, "w") as f:
            json.dump(extraction_data, f, indent=2, default=str)

        console.print(f"\n[green]✓ Saved enriched data to:[/green] {output_path}")

        # Regenerate Obsidian files if requested
        if regenerate and summary['enriched'] > 0:
            console.print("\n[bold]Regenerating Obsidian files...[/bold]")

            vault_path = config.vault_path
            template_dir = Path("templates")

            generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

            with console.status("[bold green]Generating Obsidian files..."):
                generated = generator.generate_batch(enriched_bottles, dry_run=False)

            console.print(f"[green]✓ Regenerated {len(generated)} files[/green]")

    except Exception as e:
        console.print(f"[red]Lookup failed:[/red] {e}")
        logger.exception("Lookup command failed")
        ctx.exit(1)


@cli.command()
@click.argument("input_file", type=Path)
@click.option("--skip-enrichment", is_flag=True, help="Skip metadata enrichment step")
@click.option("--output", "-o", type=Path, help="Output JSON file (default: temp file)")
@click.option("--commit/--no-commit", default=False, help="Auto-commit to git")
@click.pass_context
def pipeline(ctx, input_file, skip_enrichment, output, commit):
    """
    Run full pipeline: extract → enrich → generate.

    INPUT_FILE: Path to PDF, image, or screenshot to process

    This is a convenience command that combines:
      1. extract (from PDF/image)
      2. enrich (lookup missing metadata)
      3. generate (create Obsidian files)
      4. commit (optional, with --commit flag)

    \b
    Examples:
        reserve-automation pipeline wine_list.pdf
        reserve-automation pipeline wine_list.pdf --skip-enrichment
        reserve-automation pipeline wine_list.pdf --commit
    """
    config = ctx.obj["config"]

    try:
        # Validate input file
        if not input_file.exists():
            console.print(f"[red]Error:[/red] File not found: {input_file}")
            ctx.exit(1)

        # Determine output path for extraction
        if output:
            extraction_path = output
        else:
            # Use temp file in current directory
            extraction_path = Path(f"extraction_{input_file.stem}.json")

        console.print(f"\n[bold]Pipeline: {input_file.name}[/bold]\n")

        # STEP 1: Extract
        console.print("[bold cyan]Step 1/3: Extracting bottles...[/bold cyan]")
        with console.status("[bold green]Extracting...", spinner="dots"):
            result = asyncio.run(
                extraction_pipeline(
                    input_file=input_file,
                    config=config.model_dump(),
                    input_type="auto",
                    beverage_type="auto",
                )
            )

        # Display extraction results
        _display_extraction_results(result, review=False)

        # Save extraction results
        _save_extraction_json(result, extraction_path)
        console.print(f"[green]✓ Extracted {result.total_extracted} bottles[/green]")

        if result.total_extracted == 0:
            console.print("[yellow]No bottles extracted, stopping pipeline[/yellow]")
            ctx.exit(0)

        # Load bottles for next steps
        bottles = result.bottles

        # STEP 2: Enrich (optional)
        if not skip_enrichment:
            console.print("\n[bold cyan]Step 2/3: Enriching metadata...[/bold cyan]")

            llm_config = config.llm
            llm_gateway = LLMGateway(llm_config)
            enricher = MetadataEnricher(llm_gateway)

            with console.status("[bold green]Enriching...", spinner="dots"):
                enriched_bottles, summary = asyncio.run(
                    enricher.enrich_batch(bottles)
                )

            if summary['enriched'] > 0:
                console.print(
                    f"[green]✓ Enriched {summary['enriched']} bottles, "
                    f"added {summary['total_fields_added']} fields[/green]"
                )
                bottles = enriched_bottles

                # Update extraction file with enriched data
                result.bottles = enriched_bottles
                _save_extraction_json(result, extraction_path)
            else:
                console.print("[dim]No missing fields to enrich[/dim]")
        else:
            console.print("\n[dim]Step 2/3: Skipping enrichment (--skip-enrichment)[/dim]")

        # STEP 3: Generate
        console.print("\n[bold cyan]Step 3/3: Generating Obsidian files...[/bold cyan]")

        vault_path = config.vault_path
        template_dir = Path("templates")

        generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

        with console.status("[bold green]Generating...", spinner="dots"):
            generated = generator.generate_batch(bottles, dry_run=False)

        console.print(f"[green]✓ Generated {len(generated)} files[/green]")

        # STEP 4: Commit (optional)
        if commit:
            console.print("\n[bold cyan]Step 4: Git commit...[/bold cyan]")
            console.print("[yellow]Git commit not yet implemented[/yellow]")
            # TODO: Implement git commit

        # Summary
        console.print("\n")
        console.print(Panel(
            f"[bold green]Pipeline Complete![/bold green]\n\n"
            f"Extracted: {result.total_extracted} bottles\n"
            f"Enriched: {summary['enriched'] if not skip_enrichment else 0} bottles\n"
            f"Generated: {len(generated)} files\n\n"
            f"Extraction saved to: {extraction_path}",
            title="Success"
        ))

    except Exception as e:
        console.print(f"\n[red]Pipeline failed:[/red] {e}")
        logger.exception("Pipeline error")
        ctx.exit(1)


@cli.command(name="extract-tasting")
@click.argument("image_file", type=Path)
@click.option("--template", type=click.Choice(["aws_wine", "bourbon"]), help="Template type (auto-detected if omitted)")
@click.option("--dry-run", is_flag=True, help="Preview matches without creating files")
@click.option("--auto-match-threshold", type=float, default=0.8, help="Auto-accept match score threshold (0.0-1.0)")
@click.pass_context
def extract_tasting(ctx, image_file, template, dry_run, auto_match_threshold):
    """
    Extract tasting notes from filled-out tasting card images.

    IMAGE_FILE: Path to photo of filled-out tasting card

    Supported templates:
      - aws_wine: AWS Wine Evaluation Chart (20-point scale)
      - bourbon: Bourbon Tasting Sheet (1-5 rating)

    This command will:
      1. Extract tasting notes from the image using vision LLM
      2. Match extracted wines/whiskeys to bottles in your vault
      3. Generate tasting markdown files in the correct bottle folders

    \b
    Examples:
        reserve-automation extract-tasting wine_tasting.jpg
        reserve-automation extract-tasting bourbon_card.jpg --template bourbon
        reserve-automation extract-tasting wines.jpg --dry-run
    """
    config = ctx.obj["config"]

    try:
        # Validate input file
        if not image_file.exists():
            console.print(f"[red]Error:[/red] File not found: {image_file}")
            ctx.exit(1)

        console.print(f"\n[bold]Extracting Tasting Notes: {image_file.name}[/bold]\n")

        # Initialize components
        llm_gateway = LLMGateway(config.llm)
        extractor = TastingExtractor(llm_gateway)
        matcher = BottleMatcher(config.vault_path)
        generator = TastingGenerator(
            vault_path=config.vault_path,
            templates_path=Path("templates"),
        )

        # STEP 1: Extract tasting notes from image
        console.print("[bold cyan]Step 1/3: Extracting tasting notes...[/bold cyan]")
        with console.status("[bold green]Processing image...", spinner="dots"):
            result = asyncio.run(extractor.extract_from_image(image_file, template_type=template))

        console.print(f"[green]✓ Extracted {len(result.tastings)} tasting(s) from {result.template_type} template[/green]")

        if len(result.tastings) == 0:
            console.print("[yellow]No tastings found in image[/yellow]")
            ctx.exit(0)

        # Display extracted tastings
        _display_tasting_extraction(result)

        # STEP 2: Match to bottles in vault
        console.print("\n[bold cyan]Step 2/3: Matching to vault bottles...[/bold cyan]")

        matches = []
        for tasting in result.tastings:
            console.print(f"\n[dim]Searching for:[/dim] {tasting.bottle_name}")

            best_match = matcher.find_best_match(
                tasting.bottle_name,
                tasting.beverage_type,
                auto_accept_threshold=auto_match_threshold,
            )

            if best_match:
                matches.append((tasting, best_match))
                console.print(f"[green]✓ Matched:[/green] {best_match.folder_path.name} (score: {best_match.score:.2f})")
            else:
                console.print(f"[red]✗ No match found[/red]")

        if len(matches) == 0:
            console.print("\n[red]No bottles matched. Cannot generate tasting files.[/red]")
            console.print("\n[yellow]Hint:[/yellow] Check bottle names or adjust --auto-match-threshold")
            if not dry_run:
                ctx.exit(1)
            else:
                # In dry-run mode, show what was extracted even if no matches
                console.print("\n[dim]Dry-run mode: Continuing to show extracted data...[/dim]")

        console.print(f"\n[green]✓ Matched {len(matches)}/{len(result.tastings)} tastings[/green]")

        # STEP 3: Generate tasting files
        console.print("\n[bold cyan]Step 3/3: Generating tasting files...[/bold cyan]")

        if dry_run:
            console.print("[dim]DRY RUN: Preview only, no files will be created[/dim]\n")

        generated_paths = generator.generate_batch(matches, dry_run=dry_run)

        # Display results
        if dry_run:
            console.print(f"\n[yellow]Would create {len(generated_paths)} tasting files:[/yellow]")
        else:
            console.print(f"\n[green]✓ Created {len(generated_paths)} tasting files:[/green]")

        for path in generated_paths:
            console.print(f"  • {path}")

        # Summary
        console.print("\n")
        console.print(Panel(
            f"[bold green]Tasting Extraction Complete![/bold green]\n\n"
            f"Extracted: {len(result.tastings)} tasting(s)\n"
            f"Matched: {len(matches)} bottle(s)\n"
            f"Generated: {len(generated_paths)} file(s)\n"
            f"Template: {result.template_type}",
            title="Success" if not dry_run else "Dry Run"
        ))

    except Exception as e:
        console.print(f"\n[red]Tasting extraction failed:[/red] {e}")
        logger.exception("Tasting extraction error")
        ctx.exit(1)


def _display_tasting_extraction(result):
    """Display extracted tasting notes."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Bottle", style="cyan")
    table.add_column("Taster")
    table.add_column("Date")
    table.add_column("Score", justify="right")
    table.add_column("Type")

    for tasting in result.tastings:
        table.add_row(
            tasting.bottle_name,
            tasting.taster_name,
            tasting.tasting_date.isoformat(),
            f"{tasting.total_score()}/{tasting.max_score()}",
            tasting.beverage_type,
        )

    console.print(table)


@cli.command(name="find-labels")
@click.option("--beverage", type=click.Choice(["wine", "whiskey", "all"]), default="all", help="Beverage type filter")
@click.option("--missing-only", is_flag=True, help="Only find labels for bottles without existing label images")
@click.option("--limit", type=int, help="Limit number of bottles to process")
@click.option("--dry-run", is_flag=True, help="Preview search queries without downloading")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.pass_context
def find_labels(ctx, beverage, missing_only, limit, dry_run, yes):
    """
    Find and download bottle label images for vault bottles.

    Searches web for official bottle label images and saves them to bottle folders.

    Uses web search + LLM to find high-quality label images from:
      - Official distillery/winery websites
      - Retailer sites (Total Wine, Binny's, etc.)
      - Review sites and databases

    \b
    Examples:
        reserve-automation find-labels --missing-only
        reserve-automation find-labels --beverage whiskey --limit 5
        reserve-automation find-labels --dry-run
    """
    config = ctx.obj["config"]

    try:
        console.print("\n[bold]Finding Bottle Label Images[/bold]\n")

        # Read bottles from vault
        vault_reader = VaultReader(config.vault_path)

        beverage_filter = None if beverage == "all" else beverage
        bottles = vault_reader.read_all_bottles(beverage_type=beverage_filter)

        if len(bottles) == 0:
            console.print("[yellow]No bottles found in vault[/yellow]")
            ctx.exit(0)

        console.print(f"Found {len(bottles)} bottles in vault")

        # Initialize components
        searcher = BottleLabelSearcher()
        llm_gateway = LLMGateway(config.llm)
        llm_finder = LLMLabelFinder(llm_gateway)

        # Filter to bottles missing labels if requested
        if missing_only:
            bottles_to_process = []
            for bottle in bottles:
                folder_path = _get_bottle_folder_from_name(bottle, config.vault_path)
                if folder_path and not searcher.has_label(folder_path):
                    bottles_to_process.append(bottle)
            console.print(f"Filtering to {len(bottles_to_process)} bottles missing labels")
        else:
            bottles_to_process = bottles

        # Apply limit
        if limit and limit < len(bottles_to_process):
            bottles_to_process = bottles_to_process[:limit]
            console.print(f"Limited to first {limit} bottles")

        if len(bottles_to_process) == 0:
            console.print("[green]All bottles already have labels![/green]")
            ctx.exit(0)

        # Display bottles to process
        console.print(f"\n[bold cyan]Processing {len(bottles_to_process)} bottles[/bold cyan]\n")

        if dry_run:
            console.print("[yellow]DRY RUN: Showing search queries only[/yellow]\n")
            for bottle in bottles_to_process:
                query = searcher.construct_search_query(bottle)
                console.print(f"• {bottle.producer} {bottle.name} → [dim]{query}[/dim]")
            ctx.exit(0)

        # Process each bottle
        if not yes:
            console.print("\n[yellow]⚠ Label finding requires internet access and may take a while[/yellow]")
            console.print("[dim]Tip: Use Ctrl+C to skip to next bottle[/dim]\n")

            if not click.confirm("Continue?"):
                ctx.exit(0)

        # Initialize automatic mode components
        label_processor = None
        obsidian_updater = None
        if yes:
            label_processor = LabelImageProcessor(llm_gateway)
            obsidian_updater = ObsidianUpdater(config.vault_path)

        total_found = 0
        total_downloaded = 0
        total_skipped = 0
        total_cropped = 0
        total_updated = 0
        total_needs_review = 0
        review_log = []  # List of (bottle_name, issue, details) tuples

        for i, bottle in enumerate(bottles_to_process, 1):
            console.print(f"\n[bold cyan][{i}/{len(bottles_to_process)}] {bottle.producer} - {bottle.name}[/bold cyan]")

            # Get bottle folder
            folder_path = _get_bottle_folder_from_name(bottle, config.vault_path)
            if not folder_path:
                console.print("[red]  ✗ Could not find bottle folder[/red]")
                total_skipped += 1
                continue

            # Check if already has label
            if searcher.has_label(folder_path):
                console.print("[dim]  ✓ Already has label image[/dim]")
                total_skipped += 1
                continue

            try:
                # Use LLM with web search tools to find images
                console.print(f"  [dim]Searching web for label images...[/dim]")

                # Define async function for finding images
                async def find_images_async():
                    if yes and label_processor:
                        # Automatic mode: score and filter images
                        return await llm_finder.find_and_score_label_images(bottle, label_processor)
                    else:
                        # Interactive mode: use existing behavior
                        return await llm_finder.find_label_images(bottle)

                with console.status("  [bold green]LLM searching...", spinner="dots"):
                    images = asyncio.run(find_images_async())

                if not images:
                    console.print("  [yellow]⚠ No images found[/yellow]")
                    if yes:
                        bottle_name = f"{bottle.producer} - {bottle.name}"
                        if bottle.year:
                            bottle_name += f" - {bottle.year}"
                        review_log.append((
                            bottle_name,
                            "no_images" if not yes or not label_processor else "no_quality_images",
                            "No suitable images found" if not yes or not label_processor else "No images scored >= 7.0"
                        ))
                        total_needs_review += 1
                    total_skipped += 1
                    continue

                # Display images based on mode
                if yes:
                    # Automatic mode: show scored results and auto-select
                    console.print(f"  [green]✓ Found {len(images)} quality images (>= 7.0)[/green]")

                    # Auto-select highest scored image
                    selected_image = images[0]
                    console.print(
                        f"  [dim]Selected: {selected_image['url']} "
                        f"(score: {selected_image.get('score', 'N/A'):.1f}/10)[/dim]"
                    )
                    console.print(f"  [dim]Source: {selected_image['source']}[/dim]\n")
                else:
                    # Interactive mode: display for user selection
                    console.print(f"  [green]✓ Found {len(images)} images[/green]\n")
                    console.print("  [bold]Select an image to download:[/bold]")
                    for idx, img in enumerate(images, 1):
                        console.print(f"    [{idx}] {img['url']}")
                        console.print(f"        [dim]Source: {img['source']} - {img.get('description', '')}[/dim]")

                    console.print(f"    [0] Skip this bottle")
                    console.print()

                    # Get user selection
                    choice = click.prompt("  Enter choice", type=int, default=0)

                    if choice == 0:
                        console.print("  [dim]Skipping[/dim]")
                        total_skipped += 1
                        continue

                    if choice < 1 or choice > len(images):
                        console.print("  [red]Invalid choice, skipping[/red]")
                        total_skipped += 1
                        continue

                    # Download selected image
                    selected_image = images[choice - 1]
                label_path = searcher.get_label_path(folder_path)

                console.print(f"  [dim]Downloading from {selected_image['source']}...[/dim]")

                success = searcher.download_image(selected_image['url'], label_path)
                if not success:
                    console.print(f"  [red]✗ Download failed[/red]")
                    if yes:
                        bottle_name = f"{bottle.producer} - {bottle.name}"
                        if bottle.year:
                            bottle_name += f" - {bottle.year}"
                        review_log.append((
                            bottle_name,
                            "download_failed",
                            f"URL: {selected_image['url']}"
                        ))
                        total_needs_review += 1
                    total_skipped += 1
                    continue

                console.print(f"  [green]✓ Downloaded to {label_path}[/green]")
                total_downloaded += 1
                total_found += len(images)

                # Automatic mode: crop and update frontmatter
                if yes and label_processor and obsidian_updater:
                    # Save original image as label_original.jpg for manual review
                    original_path = label_path.parent / "label_original.jpg"
                    import shutil
                    shutil.copy2(label_path, original_path)
                    console.print(f"  [dim]Saved original as {original_path.name}[/dim]")
                    bottle_name = f"{bottle.producer} - {bottle.name}"
                    if bottle.year:
                        bottle_name += f" - {bottle.year}"

                    # Detect label bounds using computer vision first, LLM as fallback
                    console.print(f"  [dim]Detecting label bounds (computer vision)...[/dim]")

                    image_bytes = label_path.read_bytes()
                    bounds = label_processor.detect_label_bounds_cv(image_bytes)

                    # If CV detection fails, try LLM as fallback
                    if not bounds:
                        console.print(f"  [dim]CV detection failed, trying LLM fallback...[/dim]")

                        async def detect_bounds_async():
                            return await label_processor.detect_label_bounds(image_bytes, bottle)

                        bounds = asyncio.run(detect_bounds_async())

                    if bounds:
                        console.print(f"  [dim]Cropping to label...[/dim]")

                        cropped_path = label_processor.crop_to_label(label_path, bounds)

                        if cropped_path:
                            # Validate crop quality
                            console.print(f"  [dim]Validating crop quality...[/dim]")

                            async def validate_crop_async():
                                cropped_bytes = cropped_path.read_bytes()
                                return await label_processor.validate_crop_quality(cropped_bytes, bottle)

                            crop_ok = asyncio.run(validate_crop_async())

                            if crop_ok:
                                console.print(f"  [green]✓ Cropped label image (quality validated)[/green]")
                                total_cropped += 1
                            else:
                                console.print(f"  [yellow]⚠ Crop quality low, restoring original[/yellow]")
                                # Restore original (which was saved as label_original.jpg)
                                import shutil
                                shutil.copy2(original_path, label_path)
                                review_log.append((
                                    bottle_name,
                                    "crop_quality_low",
                                    "Check label_original.jpg for comparison"
                                ))
                                total_needs_review += 1
                        else:
                            console.print(f"  [yellow]⚠ Crop failed, saved uncropped[/yellow]")
                            review_log.append((
                                bottle_name,
                                "crop_failed",
                                f"Bounds: {bounds}"
                            ))
                            total_needs_review += 1
                    else:
                        console.print(f"  [yellow]⚠ Could not detect label, saved uncropped[/yellow]")
                        review_log.append((
                            bottle_name,
                            "detection_failed",
                            "Both CV and LLM detection failed"
                        ))
                        total_needs_review += 1

                    # Update Obsidian frontmatter
                    console.print(f"  [dim]Updating Obsidian metadata...[/dim]")

                    bottle_file = obsidian_updater.get_bottle_file_path(folder_path)
                    if bottle_file:
                        update_success = obsidian_updater.update_label_field(
                            bottle_file,
                            "labels/label.jpg"
                        )

                        if update_success:
                            console.print(f"  [green]✓ Updated Label field in Obsidian[/green]")
                            total_updated += 1
                        else:
                            console.print(f"  [yellow]⚠ Failed to update frontmatter[/yellow]")
                            review_log.append((
                                bottle_name,
                                "frontmatter_failed",
                                str(bottle_file)
                            ))
                            total_needs_review += 1
                    else:
                        console.print(f"  [yellow]⚠ Could not find bottle markdown file[/yellow]")
                        review_log.append((
                            bottle_name,
                            "file_not_found",
                            str(folder_path)
                        ))
                        total_needs_review += 1

            except KeyboardInterrupt:
                console.print("\n  [yellow]Skipped by user[/yellow]")
                total_skipped += 1
                continue
            except Exception as e:
                console.print(f"  [red]✗ Error: {e}[/red]")
                logger.exception(f"Error processing {bottle.producer} {bottle.name}")
                if yes:
                    bottle_name = f"{bottle.producer} - {bottle.name}"
                    if bottle.year:
                        bottle_name += f" - {bottle.year}"
                    review_log.append((
                        bottle_name,
                        "processing_error",
                        str(e)
                    ))
                    total_needs_review += 1
                total_skipped += 1
                continue

        # Write review log if there are items needing review
        if review_log and yes:
            from datetime import datetime
            log_path = Path.cwd() / "label_review.log"

            try:
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write("# Bottles Needing Manual Review\n")
                    f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                    for bottle_name, issue, details in review_log:
                        f.write(f"- {bottle_name}\n")
                        f.write(f"  Issue: {issue}\n")
                        f.write(f"  Details: {details}\n\n")

                console.print(f"\n[yellow]⚠ {len(review_log)} bottles need manual review[/yellow]")
                console.print(f"[dim]See {log_path} for details[/dim]")
            except Exception as e:
                logger.error(f"Failed to write review log: {e}")

        # Summary
        console.print("\n")
        if yes:
            # Automatic mode summary
            console.print(Panel(
                f"[bold]Label Finding Complete[/bold]\n\n"
                f"Processed: {len(bottles_to_process)} bottles\n"
                f"Found: {total_found} images\n"
                f"Downloaded: {total_downloaded} images\n"
                f"Cropped: {total_cropped} images\n"
                f"Updated: {total_updated} in Obsidian\n"
                f"Needs review: {total_needs_review} bottles",
                title="Summary"
            ))
        else:
            # Interactive mode summary
            console.print(Panel(
                f"[bold]Label Finding Complete[/bold]\n\n"
                f"Processed: {len(bottles_to_process)} bottles\n"
                f"Found: {total_found} images\n"
                f"Downloaded: {total_downloaded} images",
                title="Summary"
            ))

        searcher.close()

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        ctx.exit(0)
    except Exception as e:
        console.print(f"\n[red]Label finding failed:[/red] {e}")
        logger.exception("Label finding error")
        ctx.exit(1)


def _get_bottle_folder_from_name(bottle: BottleMetadata, vault_path: Path) -> Optional[Path]:
    """Get bottle folder path from bottle metadata."""
    # Construct expected folder name
    parts = [bottle.producer, bottle.name]
    if bottle.year:
        parts.append(str(bottle.year))
    folder_name = " - ".join(parts)

    # Search in appropriate cellar directory
    if bottle.type == "wine":
        cellar_dir = vault_path / "1_Wines"
    else:
        cellar_dir = vault_path / "1_Whiskeys"

    # Find matching folder
    for folder in cellar_dir.glob("*"):
        if folder.is_dir() and folder.name == folder_name:
            return folder

    return None


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


@cli.command(name="add-from-image")
@click.argument("image_path", type=Path)
@click.option("--beverage", type=click.Choice(["wine", "whiskey"]), help="Beverage type hint")
@click.option("--year", type=int, help="Vintage/year if not visible on label")
@click.option("--price", type=float, help="Purchase price")
@click.option("--dry-run", is_flag=True, help="Preview extraction without creating file")
@click.pass_context
def add_from_image(ctx, image_path, beverage, year, price, dry_run):
    """
    Add a bottle to your vault from a label image.

    Takes a photo of a bottle/label, extracts metadata using vision LLM,
    enriches with web search, and generates an Obsidian note.

    The provided image is automatically saved as the bottle's label.

    \b
    Examples:
        reserve-automation add-from-image photo.jpg
        reserve-automation add-from-image label.png --beverage wine
        reserve-automation add-from-image bottle.jpg --year 2019 --price 45.99
        reserve-automation add-from-image image.jpg --dry-run  # Preview only
    """
    config = ctx.obj["config"]

    try:
        # Validate image exists
        if not image_path.exists():
            console.print(f"[red]Error:[/red] Image not found: {image_path}")
            ctx.exit(1)

        vault_path = config.vault_path
        if not vault_path:
            console.print("[red]Error:[/red] Vault path not configured")
            ctx.exit(1)

        console.print(f"\n[bold]Adding bottle from image:[/bold] {image_path.name}\n")

        # Initialize components
        llm_config = config.llm
        llm_gateway = LLMGateway(llm_config)
        image_extractor = ImageMetadataExtractor(llm_gateway)
        enricher = MetadataEnricher(llm_gateway)

        # Extract metadata from image
        with console.status("[bold green]Extracting metadata from label..."):
            bottle, extraction_meta = asyncio.run(
                image_extractor.extract_from_image(image_path, beverage)
            )

        if not bottle:
            error = extraction_meta.get("error", "Unknown error")
            console.print(f"[red]✗ Extraction failed:[/red] {error}")
            ctx.exit(1)

        # Display extracted metadata
        console.print(Panel(
            f"[cyan]Producer:[/cyan] {bottle.producer}\n"
            f"[cyan]Name:[/cyan] {bottle.name}\n"
            f"[cyan]Year:[/cyan] {bottle.year or '[yellow]MISSING[/yellow]'}\n"
            f"[cyan]Type:[/cyan] {bottle.beverage_type or bottle.type}\n"
            f"[cyan]Region:[/cyan] {bottle.region or '(will enrich)'}\n"
            f"[cyan]Variety:[/cyan] {', '.join(bottle.variety) if bottle.variety else '(will enrich)'}\n"
            f"[cyan]Confidence:[/cyan] {extraction_meta.get('confidence', 'unknown')}",
            title="Extracted from Label",
            border_style="green"
        ))

        # Handle missing year
        if not bottle.year and not year:
            if extraction_meta.get("missing_year"):
                console.print("\n[yellow]⚠ Year/vintage not visible on label[/yellow]")
                year_input = click.prompt(
                    "Enter vintage/year (or press Enter to skip)",
                    type=int,
                    default=0,
                    show_default=False
                )
                if year_input > 0:
                    bottle.year = year_input
        elif year:
            # User provided year via CLI
            bottle.year = year

        # Set price if provided
        if price:
            bottle.price = price

        # Enrich metadata with web search
        console.print("\n[bold]Enriching metadata with web search...[/bold]")
        with console.status("[bold green]Searching web for bottle details..."):
            enriched_bottle, enrich_meta = asyncio.run(
                enricher.verify_bottle(bottle)
            )

        if enrich_meta.get("verified"):
            changes = enrich_meta.get("changes", {})
            if changes:
                console.print(f"\n[green]✓ Found {len(changes)} additional details:[/green]")
                for field, change in changes.items():
                    console.print(f"  • {field}: {change['new']}")
            else:
                console.print("\n[green]✓ Metadata verified[/green]")

        # Display final metadata
        console.print("\n")
        console.print(Panel(
            f"[cyan]Producer:[/cyan] {enriched_bottle.producer}\n"
            f"[cyan]Name:[/cyan] {enriched_bottle.name}\n"
            f"[cyan]Year:[/cyan] {enriched_bottle.year or '[yellow]Not specified[/yellow]'}\n"
            f"[cyan]Type:[/cyan] {enriched_bottle.beverage_type or enriched_bottle.type}\n"
            f"[cyan]Country:[/cyan] {enriched_bottle.country or '[dim]?[/dim]'}\n"
            f"[cyan]Region:[/cyan] {enriched_bottle.region or '[dim]?[/dim]'}\n"
            f"[cyan]Variety:[/cyan] {', '.join(enriched_bottle.variety) if enriched_bottle.variety else '[dim]?[/dim]'}\n"
            f"[cyan]Price:[/cyan] ${enriched_bottle.price:.2f}",
            title="Final Metadata",
            border_style="blue"
        ))

        if dry_run:
            console.print("\n[yellow]DRY RUN - No files created[/yellow]")
            ctx.exit(0)

        # Generate Obsidian file
        console.print("\n[bold]Generating Obsidian note...[/bold]")
        template_dir = Path("templates")
        generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

        generated_files = generator.generate_batch([enriched_bottle], dry_run=False)

        if generated_files:
            generated_path = generated_files[0]
            console.print(f"[green]✓ Created:[/green] {generated_path}")

            # Save label image
            bottle_folder = generated_path.parent
            labels_dir = bottle_folder / "labels"
            labels_dir.mkdir(exist_ok=True)

            label_dest = labels_dir / "label.jpg"

            # Copy and convert image
            from PIL import Image
            import shutil

            img = Image.open(image_path)
            # Convert to RGB if needed
            if img.mode in ('P', 'RGBA', 'LA'):
                if img.mode == 'P':
                    img = img.convert('RGB')
                else:
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
                    img = rgb_img

            img.save(label_dest, 'JPEG', quality=95, optimize=True)
            console.print(f"[green]✓ Saved label:[/green] {label_dest}")

            # Update Label field in Obsidian
            obsidian_updater = ObsidianUpdater(vault_path)
            if obsidian_updater.update_label_field(generated_path, "labels/label.jpg"):
                console.print("[green]✓ Updated Label field in note[/green]")

            console.print(f"\n[bold green]✓ Bottle added successfully![/bold green]")
        else:
            console.print("[red]✗ Failed to generate Obsidian file[/red]")
            ctx.exit(1)

    except Exception as e:
        console.print(f"[red]Add from image failed:[/red] {e}")
        logger.exception("Add from image command failed")
        ctx.exit(1)


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


@cli.command("validate-schema")
@click.pass_context
def validate_schema(ctx):
    """Validate code against Obsidian FileClass schemas.

    Checks that Python models, Jinja templates, and web forms
    match the Obsidian FileClass definitions (single source of truth).
    """
    try:
        config = ctx.obj["config"]
        project_root = Path(__file__).parent.parent.parent

        from .validation.schema_validator import SchemaValidator

        validator = SchemaValidator(
            vault_path=config.vault_path,
            project_root=project_root
        )

        success = validator.print_report()

        if not success:
            console.print("\n[yellow]💡 Tip: The Obsidian FileClass definitions are the single source of truth.[/yellow]")
            console.print("[yellow]   Update code to match the FileClass, or update the FileClass if it's incorrect.[/yellow]")
            ctx.exit(1)

    except Exception as e:
        console.print(f"[red]Schema validation failed:[/red] {e}")
        logger.exception("Validate schema command failed")
        ctx.exit(1)


if __name__ == "__main__":
    main()
