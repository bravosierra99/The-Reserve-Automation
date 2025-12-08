# The Reserve Automation

Bottle ingestion automation for [The Reserve](../the-reserve/) spirits collection.

**Status:** 🚀 Phase 1.5 - Tasting Card Extraction Ready!

## Overview

The Reserve Automation is a Python-based CLI tool and (future) web application for automating bottle metadata extraction and tasting management. It uses local and cloud LLMs to parse bottle information from PDFs, images, and other sources, then generates Obsidian-compatible markdown files for your spirits collection.

### Features

**Phase 1: CLI Tool** ✅ Core Features Working!
- ✅ Parse PDFs (sommelier lists, wine catalogs)
- ✅ Extract data from images (labels, screenshots)
- ✅ LLM-based structured data extraction
- ✅ Confidence scoring and review workflows
- ✅ Metadata enrichment using LLM knowledge
- ✅ Generate Obsidian markdown files
- ✅ **Extract tasting notes from physical tasting cards** (AWS Wine Chart, Bourbon Sheet)
- ✅ Fuzzy bottle matching for tasting notes
- 🚧 Git integration with the-reserve repository (partial)

**Future Phases:**
- 🌐 Web search API integration (Tavily, etc.)
- 🏷️ Label image finding and cropping
- 🖥️ Web interface for uploads and management
- 👥 Multi-user tasting sessions
- 📊 Statistics and reporting

## Architecture

See [DESIGN.md](DESIGN.md) for comprehensive technical documentation.

**Key Design Principles:**
- **LLM Agnostic**: Swap between local (LM Studio, Ollama) and cloud (Anthropic, OpenAI) providers
- **Config-Driven**: All behavior controlled via YAML files
- **Incremental Processing**: Each stage runs independently for easy debugging
- **Future-Proof**: Designed to support web API, job queues, and multi-user features

## Installation

### Prerequisites

- Python 3.11 or higher
- [UV](https://github.com/astral-sh/uv) package manager
- [LM Studio](https://lmstudio.ai/) (for local LLM inference) or cloud LLM API keys
- [the-reserve](https://github.com/bravosierra99/the-reserve) repository cloned locally

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/bravosierra99/The-Reserve-Automation.git
   cd The-Reserve-Automation
   ```

2. **Install with UV:**
   ```bash
   # Install dependencies
   uv sync

   # Install in development mode
   uv pip install -e .
   ```

3. **Initialize configuration:**
   ```bash
   # Create user config from template
   reserve-automation config init

   # Edit config/user.yaml and set:
   # - paths.vault: /path/to/the-reserve
   # - LLM base URLs if LM Studio is on another machine
   ```

4. **Set up LM Studio** (for local inference):
   - Download and install [LM Studio](https://lmstudio.ai/)
   - Load a vision model (e.g., llava-v1.6-34b) for OCR tasks
   - Load a text model (e.g., llama-3.1-70b-instruct) for extraction
   - Start the API server (default: http://localhost:1234)
   - Update `config/llm.yaml` with your model names

5. **Validate configuration:**
   ```bash
   reserve-automation config validate
   ```

## Usage

### CLI Commands

```bash
# Show help
reserve-automation --help

# Extract bottles from a PDF
reserve-automation extract sommelier_list.pdf

# Extract from an image with specific type
reserve-automation extract label.jpg --type image --beverage whiskey

# Generate Obsidian files from extraction results
reserve-automation generate extraction.json --dry-run  # Preview what will be created
reserve-automation generate extraction.json            # Create files in vault

# Lookup missing metadata using LLM (for extraction JSON files)
reserve-automation lookup extraction.json              # Enrich missing fields
reserve-automation lookup extraction.json --fields country region  # Only specific fields
reserve-automation lookup extraction.json --regenerate # Enrich + regenerate Obsidian files

# Enrich bottles already in your vault
reserve-automation enrich-vault                        # Enrich all bottles in vault
reserve-automation enrich-vault --beverage wine        # Only wines
reserve-automation enrich-vault --dry-run              # Preview what would change

# Run full pipeline (extract → enrich → generate)
reserve-automation pipeline wine_list.pdf              # Full automated pipeline
reserve-automation pipeline wine_list.pdf --skip-enrichment  # Skip enrichment step

# Extract tasting notes from filled-out tasting cards
reserve-automation extract-tasting wine_tasting.jpg    # Extract from image (auto-detects template)
reserve-automation extract-tasting bourbon_card.jpg --template bourbon  # Specify template type
reserve-automation extract-tasting tastings.jpg --dry-run  # Preview matches without creating files

# Configuration management
reserve-automation config show
reserve-automation config validate

# LLM diagnostics
reserve-automation llm list
reserve-automation llm test
```

### Example Workflows

#### Workflow 1: Process New PDF/Image (Automated Pipeline)

The simplest approach - runs everything in one command:

```bash
# Extract, enrich, and generate in one command
reserve-automation pipeline ~/Downloads/wine_list.pdf

# Skip enrichment if you want to review data first
reserve-automation pipeline wine_list.pdf --skip-enrichment
```

This runs:
1. **Extract** bottles from PDF/image
2. **Enrich** missing metadata using LLM knowledge
3. **Generate** Obsidian vault files

#### Workflow 2: Enrich Existing Vault Bottles

If you manually added bottles to your vault or want to fill in missing data:

```bash
# Preview what would be enriched (dry-run)
reserve-automation enrich-vault --dry-run

# Enrich all bottles with missing metadata
reserve-automation enrich-vault

# Enrich only wines
reserve-automation enrich-vault --beverage wine

# Enrich only specific fields
reserve-automation enrich-vault --fields country region
```

This:
- Reads bottles from your vault
- Identifies missing fields (country, region, variety, etc.)
- Uses LLM to fill in missing data
- Regenerates vault files with enriched metadata
- **Never overwrites existing data**

#### Workflow 3: Extract Tasting Notes from Cards

If you use physical tasting cards (AWS Wine Chart, Bourbon Tasting Sheet):

```bash
# Take a photo of your filled-out tasting card(s)
# Then extract the notes automatically

reserve-automation extract-tasting ~/Photos/wine_tasting.jpg

# Preview what would be created (dry-run)
reserve-automation extract-tasting bourbon_card.jpg --dry-run
```

This:
- Uses vision LLM to read your handwriting/filled-out cards
- Extracts tasting notes and scores
- Matches bottles to your vault using fuzzy matching
- Generates tasting markdown files in the correct bottle folders
- Supports AWS Wine Evaluation Chart (20-point scale) and Bourbon Tasting Sheet (1-5 rating)

**Supported tasting card templates:**
- **AWS Wine Evaluation Chart** - 20-point scale (Appearance, Aroma, Taste, Aftertaste, Overall)
- **Bourbon Tasting Sheet** - 1-5 rating scale (automatically converts to 10-point format)

#### Workflow 4: Manual Step-by-Step

For more control, run each step independently:

1. **Extract bottles from a PDF:**
   ```bash
   reserve-automation extract ~/Downloads/wine_list.pdf -o extraction.json
   ```

2. **Review and edit low-confidence extractions** (interactive prompts)

3. **Enrich missing metadata:**
   ```bash
   reserve-automation lookup extraction.json
   ```

4. **Generate Obsidian files:**
   ```bash
   reserve-automation generate extraction.json
   ```

#### Result
   - Wines: `Cellar/1_Wines/Producer - Name - Year/Producer - Name - Year.md`
   - Whiskeys: `Cellar/1_Whiskeys/Producer - Name - Year/Producer - Name - Year.md`

   Each file includes:
   - YAML frontmatter with all metadata
   - DataviewJS queries for tasting notes
   - Interactive "Add New Tasting" button
   - Proper folder structure for tastings

## Configuration

Configuration is managed via YAML files in `config/`:

- **default.yaml**: Default settings (committed to repo)
- **llm.yaml**: LLM provider configuration
- **user.yaml**: Your personal settings (gitignored)

### Key Settings

```yaml
# config/user.yaml
paths:
  vault: "/path/to/the-reserve"

llm:
  providers:
    lm_studio_text:
      base_url: "http://192.168.1.100:1234/v1"  # Your LM Studio URL

extraction:
  confidence_threshold: 0.7  # Bottles below this need review
```

### Environment Variables

Override config with environment variables:

```bash
export RESERVE_VAULT_PATH="/path/to/the-reserve"
export RESERVE_LM_STUDIO_URL="http://192.168.1.100:1234/v1"
export ANTHROPIC_API_KEY="sk-ant-..."  # For cloud fallback
```

## Development

### Project Structure

```
The-Reserve-Automation/
├── src/reserve_automation/
│   ├── cli.py              # CLI entry point
│   ├── core/               # Core data models and config
│   ├── llm/                # LLM gateway and providers
│   ├── parsers/            # PDF, image parsers
│   ├── extractors/         # LLM extraction logic
│   ├── generators/         # Obsidian file generation
│   └── utils/              # Logging and utilities
├── tests/                  # Unit and integration tests
├── config/                 # Configuration files
├── templates/              # Jinja2 templates
└── DESIGN.md              # Technical design document
```

### Running Tests

```bash
# Install dev dependencies
uv sync --all-extras

# Run all tests
pytest

# Run with coverage
pytest --cov=reserve_automation

# Run specific test file
pytest tests/unit/test_config.py
```

### Code Quality

```bash
# Format code
ruff format .

# Lint
ruff check .

# Type checking
mypy src/
```

## Roadmap

**Phase 1.1: Foundation** ✅ Complete
- [x] Project scaffolding
- [x] Configuration system
- [x] Data models
- [x] CLI skeleton

**Phase 1.2: LLM Gateway** ✅ Complete
- [x] Base LLM provider interface
- [x] LM Studio provider
- [x] Anthropic provider
- [x] Task routing

**Phase 1.3: Parsers** ✅ Complete
- [x] PDF parser
- [x] Image parser
- [x] Auto-detection

**Phase 1.4: Extraction & Generation** ✅ Complete
- [x] Bottle metadata extraction from PDFs/images
- [x] Confidence scoring
- [x] Obsidian markdown generation
- [x] Template system (Jinja2)
- [x] Unit tests

**Phase 1.5: Polish & Integration** 🚧 In Progress
- [ ] Full pipeline command (extract → generate → commit)
- [ ] Git auto-commit integration
- [ ] Interactive review workflows
- [ ] Enhanced error handling
- [ ] Integration tests

**Phase 1.6-2.0:** See [DESIGN.md](DESIGN.md) for full roadmap

## Related Projects

- [the-reserve](https://github.com/bravosierra99/the-reserve) - The Obsidian vault this tool populates
- [LM Studio](https://lmstudio.ai/) - Local LLM inference

## License

MIT - See [LICENSE](LICENSE)

## Contributing

This is a personal project, but suggestions and feedback are welcome! Open an issue or submit a pull request.

---

**Built with:**
- [Python](https://python.org/) & [UV](https://github.com/astral-sh/uv)
- [Pydantic](https://docs.pydantic.dev/) for data validation
- [Click](https://click.palletsprojects.com/) for CLI
- [Rich](https://rich.readthedocs.io/) for terminal UI
- [LM Studio](https://lmstudio.ai/) for local LLM inference
