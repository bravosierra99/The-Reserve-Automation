# The Reserve Automation

Bottle ingestion automation for [The Reserve](../the-reserve/) spirits collection.

**Status:** 🚧 Phase 1.4 - Extraction & Generation Working!

## Overview

The Reserve Automation is a Python-based CLI tool and (future) web application for automating bottle metadata extraction and tasting management. It uses local and cloud LLMs to parse bottle information from PDFs, images, and other sources, then generates Obsidian-compatible markdown files for your spirits collection.

### Features

**Phase 1: CLI Tool** ✅ Core Features Working!
- ✅ Parse PDFs (sommelier lists, wine catalogs)
- ✅ Extract data from images (labels, screenshots)
- ✅ LLM-based structured data extraction
- ✅ Confidence scoring and review workflows
- ✅ Generate Obsidian markdown files
- 🚧 Git integration with the-reserve repository (partial)

**Future Phases:**
- 🌐 Web research for missing metadata
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

# Run full pipeline (extract → generate → commit)
reserve-automation pipeline wine_list.pdf --commit

# Configuration management
reserve-automation config show
reserve-automation config validate

# LLM diagnostics
reserve-automation llm list
reserve-automation llm test
```

### Example Workflow

1. **Extract bottles from a PDF:**
   ```bash
   reserve-automation extract ~/Downloads/wine_list.pdf -o extraction.json
   ```

2. **Review and edit low-confidence extractions** (interactive prompts)

3. **Generate Obsidian files:**
   ```bash
   # Preview what will be created (dry-run)
   reserve-automation generate extraction.json --dry-run

   # Generate files in vault (uses config vault path)
   reserve-automation generate extraction.json

   # Override vault path
   reserve-automation generate extraction.json --vault ~/the-reserve
   ```

4. **Result:** Bottle markdown files created in structured directories:
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
