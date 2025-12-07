# The Reserve Automation - Phase 1 Design Document

**Version:** 1.1
**Date:** 2025-12-07
**Status:** Phase 1.4 Complete - Extraction & Generation Working

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Infrastructure & Deployment](#infrastructure--deployment)
4. [Core Components](#core-components)
5. [Data Models](#data-models)
6. [LLM Integration](#llm-integration)
7. [Processing Pipeline](#processing-pipeline)
8. [Configuration System](#configuration-system)
9. [CLI Interface](#cli-interface)
10. [Testing Strategy](#testing-strategy)
11. [Development Roadmap](#development-roadmap)
12. [Future Phases](#future-phases)

---

## Executive Summary

### Project Vision

The Reserve Automation is a multi-phase project to automate bottle ingestion, metadata extraction, and tasting management for The Reserve spirits collection (Obsidian vault). The long-term goal is a self-hosted web application with multi-user support, local LLM integration, and comprehensive tasting session management.

### Phase 1 Goals

Build a robust CLI tool for:
- Parsing bottle data from PDFs, images, and screenshots
- LLM-based extraction of structured metadata
- Web research for missing information (future)
- Generation of Obsidian-compatible markdown files
- Git integration with the-reserve repository

### Key Principles

1. **LLM Agnostic**: Abstract LLM providers to allow switching between local (LM Studio, Ollama) and cloud (Anthropic, OpenAI)
2. **Configuration-Driven**: All behavior controllable via YAML config files
3. **Incremental Processing**: Each stage can run independently for debugging/iteration
4. **Quality First**: Confidence scoring and review workflows for uncertain extractions
5. **Future-Proof Architecture**: Design to support web API, job queues, and multi-user features in later phases

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Phase 1: CLI Tool                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Input      │───▶│  Extraction  │───▶│  Generation  │  │
│  │   Parsers    │    │   Pipeline   │    │   Engine     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    │         │
│         ▼                    ▼                    ▼         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              LLM Gateway (Abstraction)                │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ LM Studio  │  │ Anthropic  │  │  OpenAI    │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Data Layer (JSON intermediate files)          │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │      Output: Obsidian Files + Git Integration        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Purpose | Dependencies |
|-----------|---------|--------------|
| **CLI** | User interface, command orchestration | Click, Rich |
| **Parsers** | Extract text/images from PDFs, images | pdfplumber, pytesseract, Pillow |
| **LLM Gateway** | Abstract LLM providers, route tasks | httpx, anthropic, openai SDKs |
| **Extractors** | Use LLMs to extract structured data | LLM Gateway, Pydantic |
| **Enrichers** | Web scraping for missing metadata | requests, BeautifulSoup4 |
| **Generators** | Create Obsidian markdown files | Jinja2, GitPython |
| **Config System** | YAML-based configuration | PyYAML, Pydantic |

---

## Infrastructure & Deployment

### Current Setup (Phase 1)

**Development Environment:**
- Python 3.11+
- Local development on Windows/Linux
- LM Studio running on user's PC (GPU access)
- The-reserve git repository locally cloned

**Initial Deployment:**
- CLI tool runs on developer machine
- No server deployment required for Phase 1

### Future Infrastructure (Phases 2+)

```
┌───────────────────────────────────────────────────────────┐
│  User's PC                                                 │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ LM Studio (GPU-accelerated)                         │  │
│  │ - Vision models (llava, bakllava)                   │  │
│  │ - Text models (llama3.1-70b)                        │  │
│  │ - API: http://192.168.x.x:1234/v1                   │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
                           ↕ HTTP API
┌───────────────────────────────────────────────────────────┐
│  Proxmox Server                                            │
│                                                            │
│  Option A: Single LXC Container (Initial)                 │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ reserve-automation                                   │  │
│  │ - Docker Compose:                                    │  │
│  │   - FastAPI (web server)                             │  │
│  │   - Celery (workers)                                 │  │
│  │   - Redis (task queue)                               │  │
│  │   - SQLite (data)                                    │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  Option B: Separate LXCs (Production)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Traefik  │  │   API    │  │ Workers  │  │  Redis   │  │
│  │ (Proxy)  │  │ FastAPI  │  │ Celery   │  │  +Data   │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└───────────────────────────────────────────────────────────┘
```

### Authentication Strategy (Future)

```yaml
auth_levels:
  guest:
    network: local_only  # 192.168.x.x, 10.x.x.x
    permissions:
      - view_bottles
      - upload_files
      - review_pending
    restrictions:
      - no_delete
      - no_edit_approved

  user:
    network: any
    permissions:
      - all_guest
      - edit_own
      - create_tastings
      - manage_bottles
    restrictions:
      - no_delete_others
      - no_admin

  admin:
    network: any
    permissions:
      - everything
```

---

## Core Components

### 1. Input Parsers

**Purpose:** Extract raw text and images from various input formats.

**Supported Input Types:**
- PDF documents (sommelier lists, wine catalogs)
- Images (photos of labels, lists)
- Screenshots (phone captures, desktop screenshots)

**Implementation:**

```python
# parsers/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union

class ParserResult:
    """Parsed input data"""
    raw_text: str
    images: list[bytes]
    metadata: dict
    source_type: str

class BaseParser(ABC):
    @abstractmethod
    async def parse(self, input_file: Path) -> ParserResult:
        pass

    @abstractmethod
    def can_parse(self, input_file: Path) -> bool:
        """Check if this parser can handle the file"""
        pass

# parsers/pdf.py
class PDFParser(BaseParser):
    """Parse PDF files using pdfplumber + OCR fallback"""

    async def parse(self, input_file: Path) -> ParserResult:
        # 1. Try pdfplumber text extraction
        text = self._extract_text(input_file)

        # 2. If text is sparse, use OCR on rendered pages
        if self._is_sparse(text):
            text = await self._ocr_pages(input_file)

        # 3. Extract embedded images
        images = self._extract_images(input_file)

        return ParserResult(
            raw_text=text,
            images=images,
            metadata={'pages': self._get_page_count(input_file)},
            source_type='pdf'
        )

# parsers/image.py
class ImageParser(BaseParser):
    """Parse images using OCR"""

    async def parse(self, input_file: Path) -> ParserResult:
        # 1. Load image
        image = Image.open(input_file)

        # 2. Preprocess (deskew, denoise, enhance contrast)
        processed = self._preprocess(image)

        # 3. OCR with tesseract
        text = pytesseract.image_to_string(processed)

        return ParserResult(
            raw_text=text,
            images=[processed.tobytes()],
            metadata={'dimensions': image.size},
            source_type='image'
        )

# parsers/detector.py
class ParserDetector:
    """Auto-detect and route to correct parser"""

    def __init__(self):
        self.parsers = [
            PDFParser(),
            ImageParser(),
        ]

    async def parse(self, input_file: Path) -> ParserResult:
        for parser in self.parsers:
            if parser.can_parse(input_file):
                return await parser.parse(input_file)

        raise UnsupportedFileTypeError(f"No parser for {input_file}")
```

**Key Libraries:**
- `pdfplumber`: PDF text extraction
- `pytesseract`: OCR for images and scanned PDFs
- `Pillow (PIL)`: Image preprocessing
- `pdf2image`: Convert PDF pages to images for OCR

---

### 2. LLM Gateway

**Purpose:** Provide unified interface to multiple LLM providers with task-based routing.

**Design Goals:**
1. Provider-agnostic API
2. Automatic failover to backup providers
3. Task-based routing (vision vs text, simple vs complex)
4. Request/response logging for debugging (using loguru)
5. Cost tracking (for cloud providers)

**Architecture:**

```python
# llm/gateway.py
from typing import Optional, Literal, Any
from pydantic import BaseModel
import httpx
from loguru import logger

class LLMRequest(BaseModel):
    """Unified request format"""
    prompt: str
    system: Optional[str] = None
    images: Optional[list[bytes]] = None
    max_tokens: int = 2000
    temperature: float = 0.2
    response_format: Optional[Literal['json', 'text']] = None

class LLMResponse(BaseModel):
    """Unified response format"""
    content: str
    provider: str
    model: str
    tokens_used: int
    cost: float = 0.0
    latency_ms: float

class LLMGateway:
    """
    Central LLM abstraction layer.
    Routes requests to appropriate providers based on task type.
    """

    def __init__(self, config: dict):
        self.config = config
        self.providers = self._initialize_providers()
        self.routing = config['routing']
        self.fallback_rules = config.get('fallback', {})

    async def complete(
        self,
        task_type: str,
        prompt: str,
        system: Optional[str] = None,
        images: Optional[list[bytes]] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Execute LLM completion with automatic routing.

        Args:
            task_type: Task identifier (e.g., 'extraction', 'ocr', 'vision')
            prompt: User prompt
            system: System prompt (optional)
            images: Image data for vision tasks (optional)
            **kwargs: Additional provider-specific args

        Returns:
            LLMResponse with completion and metadata
        """
        # 1. Determine provider from routing rules
        provider_name = self.routing.get(task_type)
        if not provider_name:
            raise ValueError(f"No routing rule for task: {task_type}")

        # 2. Build request
        request = LLMRequest(
            prompt=prompt,
            system=system,
            images=images,
            **kwargs
        )

        # 3. Execute with fallback
        try:
            provider = self.providers[provider_name]
            response = await provider.complete(request)
            logger.info(f"✓ {task_type} via {provider_name}")
            return response

        except Exception as e:
            logger.error(f"✗ {provider_name} failed: {e}")

            # Try fallback if configured
            if self.fallback_rules.get('enabled'):
                fallback = self._get_fallback(provider_name, task_type)
                if fallback:
                    logger.info(f"↻ Retrying with {fallback}")
                    provider = self.providers[fallback]
                    return await provider.complete(request)

            raise

    def _initialize_providers(self) -> dict:
        """Initialize all configured providers"""
        from .providers import (
            LMStudioProvider,
            AnthropicProvider,
            OpenAIProvider,
        )

        provider_map = {
            'lm_studio': LMStudioProvider,
            'anthropic': AnthropicProvider,
            'openai': OpenAIProvider,
        }

        providers = {}
        for name, config in self.config['providers'].items():
            provider_type = config['provider']
            ProviderClass = provider_map[provider_type]
            providers[name] = ProviderClass(config)

        return providers
```

**Provider Base Class:**

```python
# llm/providers/base.py
from abc import ABC, abstractmethod

class BaseLLMProvider(ABC):
    """Abstract base for all LLM providers"""

    def __init__(self, config: dict):
        self.config = config
        self.model = config['model']
        self.timeout = config.get('timeout', 120)

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute completion request"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Test provider connectivity"""
        pass

# llm/providers/lm_studio.py
class LMStudioProvider(BaseLLMProvider):
    """
    LM Studio provider using OpenAI-compatible API.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config['base_url']
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.time()

        # Build OpenAI-compatible request
        messages = []
        if request.system:
            messages.append({'role': 'system', 'content': request.system})

        # Handle vision requests
        if request.images:
            content = [{'type': 'text', 'text': request.prompt}]
            for image in request.images:
                b64_image = base64.b64encode(image).decode()
                content.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/jpeg;base64,{b64_image}'}
                })
            messages.append({'role': 'user', 'content': content})
        else:
            messages.append({'role': 'user', 'content': request.prompt})

        # Call API
        response = await self.client.post('/chat/completions', json={
            'model': self.model,
            'messages': messages,
            'max_tokens': request.max_tokens,
            'temperature': request.temperature,
        })
        response.raise_for_status()

        data = response.json()
        latency = (time.time() - start) * 1000

        return LLMResponse(
            content=data['choices'][0]['message']['content'],
            provider='lm_studio',
            model=self.model,
            tokens_used=data['usage']['total_tokens'],
            cost=0.0,  # Free local model
            latency_ms=latency
        )

    async def health_check(self) -> bool:
        try:
            response = await self.client.get('/models')
            return response.status_code == 200
        except:
            return False
```

---

### 3. Extraction Pipeline

**Purpose:** Use LLMs to extract structured bottle data from parsed text/images.

**Process Flow:**

```
Parsed Input → LLM Extraction → Validation → Confidence Scoring → Output
```

**Implementation:**

```python
# extractors/bottle.py
from typing import List
from pydantic import ValidationError
from loguru import logger
import json

class BottleExtractor:
    """
    Extract structured bottle metadata using LLMs.
    """

    def __init__(self, llm_gateway: LLMGateway):
        self.llm = llm_gateway

    async def extract(
        self,
        parser_result: ParserResult,
        beverage_type: Literal['wine', 'whiskey', 'auto'] = 'auto'
    ) -> List[BottleMetadata]:
        """
        Extract bottle data from parsed input.

        Returns:
            List of BottleMetadata with confidence scores
        """
        # 1. Detect beverage type if auto
        if beverage_type == 'auto':
            beverage_type = await self._detect_type(parser_result.raw_text)

        # 2. Build extraction prompt
        prompt = self._build_extraction_prompt(
            text=parser_result.raw_text,
            beverage_type=beverage_type
        )

        # 3. Request structured extraction
        response = await self.llm.complete(
            task_type='extraction',
            prompt=prompt,
            system=EXTRACTION_SYSTEM_PROMPT,
            response_format='json'
        )

        # 4. Parse and validate
        try:
            bottles_data = json.loads(response.content)
            bottles = []

            for bottle_dict in bottles_data['bottles']:
                try:
                    bottle = BottleMetadata(**bottle_dict)

                    # 5. Score confidence
                    bottle.confidence = self._calculate_confidence(bottle)
                    bottle.source = parser_result.source_type

                    bottles.append(bottle)

                except ValidationError as e:
                    # Log validation errors but continue
                    logger.warning(f"Invalid bottle data: {e}")

            return bottles

        except json.JSONDecodeError:
            # LLM didn't return valid JSON
            raise ExtractionError("Failed to parse LLM response as JSON")

    def _build_extraction_prompt(
        self,
        text: str,
        beverage_type: str
    ) -> str:
        """Build extraction prompt with schema guidance"""

        schema = self._get_schema(beverage_type)

        return f"""Extract all {beverage_type} bottles from the following text.

Return a JSON array with this exact schema:
{json.dumps(schema, indent=2)}

Rules:
- Extract ALL bottles mentioned
- Use null for missing fields
- Infer year if mentioned as "vintage" or "release"
- Standardize country names (e.g., "USA" → "United States")
- Include price only if explicitly stated with currency

Text to extract from:
---
{text}
---

Return JSON only, no other text."""

    def _calculate_confidence(self, bottle: BottleMetadata) -> float:
        """
        Calculate extraction confidence based on field completeness
        and data quality.

        Score: 0.0 - 1.0
        """
        score = 0.0

        # Required fields present (0.5 points)
        if bottle.producer and bottle.name:
            score += 0.5

        # Year present and valid (0.2 points)
        if bottle.year and 1800 <= bottle.year <= 2030:
            score += 0.2

        # Type/variety specified (0.15 points)
        if bottle.beverage_type or bottle.variety:
            score += 0.15

        # Region/country specified (0.1 points)
        if bottle.region or bottle.country:
            score += 0.1

        # Price present (0.05 points)
        if bottle.price:
            score += 0.05

        return min(score, 1.0)

# extractors/confidence.py
class ConfidenceAnalyzer:
    """
    Analyze extraction confidence and flag items for review.
    """

    REVIEW_THRESHOLD = 0.7

    def analyze(
        self,
        bottles: List[BottleMetadata]
    ) -> tuple[List[BottleMetadata], List[BottleMetadata]]:
        """
        Split bottles into high-confidence and needs-review.

        Returns:
            (high_confidence, needs_review)
        """
        high_confidence = []
        needs_review = []

        for bottle in bottles:
            if bottle.confidence >= self.REVIEW_THRESHOLD:
                high_confidence.append(bottle)
            else:
                needs_review.append(bottle)

        return high_confidence, needs_review
```

**Extraction Prompts:**

```python
# llm/prompts/extraction.py

EXTRACTION_SYSTEM_PROMPT = """You are a wine and spirits expert specializing in extracting structured data from lists, catalogs, and labels.

Your task is to:
1. Identify all bottles mentioned in the input
2. Extract metadata for each bottle
3. Return well-structured JSON
4. Use null for missing information (never guess)
5. Maintain accuracy - only extract what is explicitly stated

Quality standards:
- Producer/distillery names should be capitalized correctly
- Years should be 4-digit integers
- Countries should use full names (not abbreviations)
- Prices should be numeric values only (no currency symbols)
"""

WINE_SCHEMA = {
    "type": "object",
    "properties": {
        "producer": {"type": "string", "description": "Winemaker/estate name"},
        "name": {"type": "string", "description": "Wine name"},
        "year": {"type": "integer", "description": "Vintage year", "nullable": True},
        "type": {"type": "string", "enum": ["wine"]},
        "beverage_type": {"type": "string", "description": "Red wine, White wine, Rosé, Champagne", "nullable": True},
        "variety": {"type": "string", "description": "Grape variety/blend", "nullable": True},
        "region": {"type": "string", "description": "Wine region", "nullable": True},
        "country": {"type": "string", "description": "Country of origin", "nullable": True},
        "abv": {"type": "number", "description": "Alcohol by volume", "nullable": True},
        "price": {"type": "number", "description": "Price in local currency", "nullable": True},
    },
    "required": ["producer", "name", "type"]
}

WHISKEY_SCHEMA = {
    "type": "object",
    "properties": {
        "producer": {"type": "string", "description": "Distillery name"},
        "name": {"type": "string", "description": "Whiskey name"},
        "year": {"type": "integer", "description": "Release year", "nullable": True},
        "type": {"type": "string", "enum": ["whiskey"]},
        "beverage_type": {"type": "string", "description": "Bourbon, Rye, Scotch, etc.", "nullable": True},
        "region": {"type": "string", "description": "Region/state", "nullable": True},
        "country": {"type": "string", "description": "Country of origin", "nullable": True},
        "abv": {"type": "number", "description": "Alcohol by volume", "nullable": True},
        "price": {"type": "number", "description": "Price in local currency", "nullable": True},
    },
    "required": ["producer", "name", "type"]
}
```

---

### 4. Obsidian Generator

**Purpose:** Create Obsidian-compatible markdown files from extracted bottle data.

**Output Structure:**

```
Cellar/
├── 1_Wines/
│   └── Producer - Name - Year/
│       └── Producer - Name - Year.md
├── 1_Whiskeys/
│   └── Producer - Name - Year/
│       └── Producer - Name - Year.md
```

**Implementation:**

```python
# generators/obsidian.py
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from datetime import datetime

class ObsidianGenerator:
    """
    Generate Obsidian markdown files from bottle metadata.
    """

    def __init__(self, vault_path: Path, template_dir: Path):
        self.vault_path = vault_path
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def generate_bottle_file(
        self,
        bottle: BottleMetadata
    ) -> ObsidianFile:
        """
        Generate markdown file for a bottle.

        Returns:
            ObsidianFile with path and content
        """
        # 1. Determine subdirectory
        subdir = '1_Wines' if bottle.type == 'wine' else '1_Whiskeys'

        # 2. Generate filename
        filename = self._generate_filename(bottle)

        # 3. Full path
        folder_path = self.vault_path / subdir / filename
        file_path = folder_path / f"{filename}.md"

        # 4. Render template
        template_name = f"bottle_{bottle.type}.md.j2"
        template = self.env.get_template(template_name)

        content = template.render(
            bottle=bottle,
            generated_date=datetime.now().isoformat(),
        )

        return ObsidianFile(
            file_path=str(file_path),
            content=content,
            bottle=bottle
        )

    def _generate_filename(self, bottle: BottleMetadata) -> str:
        """
        Generate Obsidian-safe filename.

        Format: Producer - Name - Year
        """
        parts = [bottle.producer, bottle.name]
        if bottle.year:
            parts.append(str(bottle.year))

        # Sanitize for filesystem
        filename = ' - '.join(parts)
        filename = self._sanitize_filename(filename)

        return filename

    def _sanitize_filename(self, name: str) -> str:
        """Remove/replace invalid filename characters"""
        # Obsidian-safe: alphanumeric, spaces, hyphens, underscores
        import re
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name)
        return name.strip()

# generators/git_ops.py
from git import Repo
from typing import List

class GitOperations:
    """
    Handle git operations for the-reserve repository.
    """

    def __init__(self, repo_path: Path):
        self.repo = Repo(repo_path)

    def commit_bottles(
        self,
        bottles: List[BottleMetadata],
        branch: str = 'tastings-backup'
    ):
        """
        Commit new bottles to repository.

        Args:
            bottles: List of added bottles
            branch: Target branch (default: tastings-backup)
        """
        # 1. Ensure on correct branch
        current_branch = self.repo.active_branch.name
        if current_branch != branch:
            self.repo.git.checkout(branch)

        # 2. Stage new files
        # Note: Must use -f to add files in .gitignore
        self.repo.git.add('-f', 'Cellar/1_Wines/', 'Cellar/1_Whiskeys/')

        # 3. Generate commit message
        message = self._generate_commit_message(bottles)

        # 4. Commit
        self.repo.index.commit(message)

        print(f"✓ Committed {len(bottles)} bottles to {branch}")

    def _generate_commit_message(self, bottles: List[BottleMetadata]) -> str:
        """Generate descriptive commit message"""
        count = len(bottles)

        if count == 1:
            b = bottles[0]
            title = f"Add bottle: {b.producer} - {b.name}"
        else:
            title = f"Add {count} bottles via automation"

        # List bottles
        body_lines = ["", "Bottles added:"]
        for b in bottles[:10]:  # Max 10 in message
            body_lines.append(f"- {b.producer} - {b.name} ({b.year or 'N/A'})")

        if count > 10:
            body_lines.append(f"- ... and {count - 10} more")

        body_lines.extend([
            "",
            "🤖 Generated with The Reserve Automation",
            "Co-Authored-By: Automation Bot <bot@reserve.local>"
        ])

        return title + "\n" + "\n".join(body_lines)
```

**Jinja2 Templates:**

```jinja2
{# templates/bottle_wine.md.j2 #}
---
fileClass: Wine
Name: "{{ bottle.producer }} - {{ bottle.name }}{% if bottle.year %} - {{ bottle.year }}{% endif %}"
Winemaker: "{{ bottle.producer }}"
WineName: "{{ bottle.name }}"
{% if bottle.year -%}
Vintage: "{{ bottle.year }}"
{% endif -%}
{% if bottle.beverage_type -%}
Type: {{ bottle.beverage_type }}
{% endif -%}
{% if bottle.variety -%}
Variety: {{ bottle.variety }}
{% endif -%}
{% if bottle.country and bottle.region -%}
Country-Region: "{{ bottle.country }} - {{ bottle.region }}"
{% elif bottle.country -%}
Country-Region: "{{ bottle.country }}"
{% endif -%}
{% if bottle.price -%}
Price: {{ bottle.price }}
{% endif -%}
Stars: --
ValueForMoney:
Inventory: 0
Buy: 0
---

## Tasting Notes

*Add tasting notes here*

## Label

Label::

---

*Imported via automation on {{ generated_date }}*
*Confidence: {{ "%.0f"|format(bottle.confidence * 100) }}%*
```

---

## Data Models

All data models use Pydantic for validation and serialization.

### Core Models

```python
# core/models.py
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal, List
from datetime import datetime
from enum import Enum

class BeverageType(str, Enum):
    """Beverage categories"""
    WINE = 'wine'
    WHISKEY = 'whiskey'

class BottleMetadata(BaseModel):
    """
    Extracted bottle information with confidence scoring.
    """
    # Core identifiers (required)
    producer: str = Field(
        ...,
        description="Winemaker/distillery name",
        min_length=1,
        max_length=200
    )
    name: str = Field(
        ...,
        description="Wine/whiskey name",
        min_length=1,
        max_length=200
    )
    type: BeverageType = Field(
        ...,
        description="Wine or whiskey"
    )

    # Optional core fields
    year: Optional[int] = Field(
        None,
        description="Vintage/release year",
        ge=1800,
        le=2030
    )
    beverage_type: Optional[str] = Field(
        None,
        description="Specific type (Red wine, Bourbon, etc.)",
        max_length=100
    )

    # Geographic
    country: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=200)

    # Wine-specific
    variety: Optional[str] = Field(
        None,
        description="Grape variety or blend"
    )
    vineyard: Optional[str] = None

    # Whiskey-specific
    age_statement: Optional[int] = Field(None, ge=0, le=100)
    proof: Optional[float] = Field(None, ge=0, le=200)
    mash_bill: Optional[str] = None
    barrel_type: Optional[str] = None

    # Common
    abv: Optional[float] = Field(None, ge=0, le=100)
    price: Optional[float] = Field(None, ge=0)

    # Metadata
    confidence: float = Field(
        0.0,
        description="Extraction confidence (0-1)",
        ge=0.0,
        le=1.0
    )
    source: str = Field(
        ...,
        description="Source of extraction (pdf, image, etc.)"
    )
    extracted_at: datetime = Field(
        default_factory=datetime.now
    )

    # Enrichment
    enriched: bool = False
    label_image_url: Optional[str] = None
    notes: Optional[str] = Field(
        None,
        description="Extraction notes or warnings"
    )

    class Config:
        use_enum_values = True

    @validator('producer', 'name')
    def strip_whitespace(cls, v):
        """Clean up string fields"""
        return v.strip() if v else v

    def to_obsidian_dict(self) -> dict:
        """Convert to Obsidian frontmatter format"""
        data = {
            'Name': f"{self.producer} - {self.name}",
            'Winemaker' if self.type == 'wine' else 'Distiller': self.producer,
        }

        if self.year:
            data['Vintage' if self.type == 'wine' else 'Year'] = self.year

        # Add non-null fields
        for field in self.__fields__:
            value = getattr(self, field)
            if value is not None and field not in ['producer', 'name', 'year', 'type']:
                data[field.replace('_', '-').title()] = value

        return data

class ExtractionResult(BaseModel):
    """
    Complete result from extraction pipeline.
    """
    bottles: List[BottleMetadata]
    source_file: str
    source_type: Literal['pdf', 'image', 'screenshot']

    # Statistics
    total_extracted: int
    high_confidence_count: int
    needs_review_count: int

    # Categorized bottles
    high_confidence: List[BottleMetadata] = []
    needs_review: List[BottleMetadata] = []

    # Processing metadata
    processing_time_seconds: float
    errors: List[str] = []
    warnings: List[str] = []

    # LLM usage
    total_tokens_used: int = 0
    total_cost: float = 0.0

    created_at: datetime = Field(default_factory=datetime.now)

    @validator('total_extracted', always=True)
    def validate_counts(cls, v, values):
        """Ensure counts match bottle list"""
        if 'bottles' in values:
            actual_count = len(values['bottles'])
            if v != actual_count:
                raise ValueError(
                    f"total_extracted ({v}) doesn't match bottles ({actual_count})"
                )
        return v

class ObsidianFile(BaseModel):
    """
    Generated Obsidian markdown file.
    """
    file_path: str = Field(..., description="Absolute path to file")
    content: str = Field(..., description="Markdown content")
    bottle: BottleMetadata

    created_at: datetime = Field(default_factory=datetime.now)

    def write(self):
        """Write file to disk"""
        from pathlib import Path

        path = Path(self.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.content, encoding='utf-8')

class ProcessingJob(BaseModel):
    """
    Job tracking for async processing (future phases).
    """
    job_id: str
    status: Literal['pending', 'processing', 'completed', 'failed']
    input_file: str
    result: Optional[ExtractionResult] = None
    error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

---

## Configuration System

### Configuration Files

```yaml
# config/default.yaml
# Default configuration (committed to repo)

# Project settings
project:
  name: "The Reserve Automation"
  version: "0.1.0"

# Paths
paths:
  vault: null  # Must be set by user
  config_dir: "config"
  templates_dir: "templates"
  cache_dir: ".cache"
  logs_dir: "logs"

# LLM Configuration (imported from llm.yaml)
llm:
  config_file: "config/llm.yaml"

# Parser settings
parsers:
  pdf:
    use_ocr_fallback: true
    ocr_language: "eng"
    min_confidence: 60

  image:
    preprocess: true
    deskew: true
    denoise: true
    enhance_contrast: true

# Extraction settings
extraction:
  confidence_threshold: 0.7
  auto_detect_type: true
  max_bottles_per_page: 50

# Git settings
git:
  default_branch: "tastings-backup"
  auto_commit: false  # Require explicit --commit flag
  commit_author: "Automation Bot"
  commit_email: "bot@reserve.local"

# Logging
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "logs/automation.log"
```

```yaml
# config/llm.yaml
# LLM provider configuration

providers:
  # Local LM Studio (primary)
  lm_studio_vision:
    provider: lm_studio
    base_url: "http://192.168.1.100:1234/v1"  # UPDATE THIS
    model: "llava-v1.6-34b"
    timeout: 180
    max_retries: 2

  lm_studio_text:
    provider: lm_studio
    base_url: "http://192.168.1.100:1234/v1"  # UPDATE THIS
    model: "llama-3.1-70b-instruct"
    timeout: 120
    max_retries: 2

  # Cloud fallbacks (optional)
  anthropic_sonnet:
    provider: anthropic
    api_key_env: "ANTHROPIC_API_KEY"
    model: "claude-sonnet-4"
    timeout: 60

  openai_gpt4:
    provider: openai
    api_key_env: "OPENAI_API_KEY"
    model: "gpt-4-turbo"
    timeout: 60

# Task routing rules
routing:
  ocr: lm_studio_vision
  extraction: lm_studio_text
  type_detection: lm_studio_text
  web_research: lm_studio_text  # or anthropic_sonnet
  quality_check: lm_studio_text

# Fallback configuration
fallback:
  enabled: true
  log_warnings: true
  rules:
    lm_studio_vision:
      - anthropic_sonnet  # Use cloud if local vision fails
    lm_studio_text:
      - anthropic_sonnet
      - openai_gpt4
```

```yaml
# config/user.yaml.example
# User-specific config (gitignored)
# Copy to user.yaml and customize

paths:
  vault: "/path/to/the-reserve"

llm:
  providers:
    lm_studio_vision:
      base_url: "http://YOUR_PC_IP:1234/v1"
    lm_studio_text:
      base_url: "http://YOUR_PC_IP:1234/v1"

# Override any settings from default.yaml
extraction:
  confidence_threshold: 0.8  # Stricter threshold
```

### Config Loading

```python
# core/config.py
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, validator

class Config(BaseModel):
    """
    Application configuration.
    Loads from multiple YAML files with precedence:
      1. user.yaml (highest priority)
      2. default.yaml
      3. Environment variables
    """

    # Paths
    vault_path: Optional[Path] = None
    config_dir: Path = Path("config")
    templates_dir: Path = Path("templates")

    # Settings
    llm: dict
    parsers: dict
    extraction: dict
    git: dict
    logging: dict

    @classmethod
    def load(cls, config_file: Optional[Path] = None) -> 'Config':
        """
        Load configuration from files.

        Args:
            config_file: Optional user config file (overrides default)

        Returns:
            Merged configuration
        """
        # 1. Load default config
        default_path = Path("config/default.yaml")
        with open(default_path) as f:
            config = yaml.safe_load(f)

        # 2. Load LLM config
        llm_path = Path(config['llm']['config_file'])
        with open(llm_path) as f:
            config['llm'] = yaml.safe_load(f)

        # 3. Load user config if exists
        user_path = config_file or Path("config/user.yaml")
        if user_path.exists():
            with open(user_path) as f:
                user_config = yaml.safe_load(f)
                config = cls._deep_merge(config, user_config)

        # 4. Override with environment variables
        config = cls._apply_env_overrides(config)

        return cls(**config)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge dictionaries"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Config._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _apply_env_overrides(config: dict) -> dict:
        """Apply environment variable overrides"""
        import os

        # Example: RESERVE_VAULT_PATH overrides paths.vault
        if vault_env := os.getenv('RESERVE_VAULT_PATH'):
            config['paths']['vault'] = vault_env

        return config

    @validator('vault_path')
    def validate_vault_path(cls, v):
        """Ensure vault path exists"""
        if v and not v.exists():
            raise ValueError(f"Vault path does not exist: {v}")
        return v
```

---

## CLI Interface

### Command Structure

```
reserve-automation
├── extract       # Extract bottles from files
├── enrich        # Enrich existing extraction (web research)
├── generate      # Generate Obsidian files
├── pipeline      # Run full pipeline (extract → enrich → generate)
├── config        # Config management
│   ├── show      # Show current config
│   ├── validate  # Validate config files
│   └── init      # Initialize user config
└── llm           # LLM diagnostics
    ├── test      # Test LLM connection
    ├── list      # List available providers
    └── health    # Health check all providers
```

### CLI Implementation

```python
# cli.py
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import track
import asyncio

console = Console()

@click.group()
@click.option('--config', type=Path, help='Config file path')
@click.option('--verbose', '-v', is_flag=True, help='Verbose logging')
@click.pass_context
def cli(ctx, config, verbose):
    """The Reserve Automation - Bottle ingestion pipeline"""
    ctx.ensure_object(dict)

    # Load configuration
    ctx.obj['config'] = Config.load(config)

    # Setup logging
    setup_logging(ctx.obj['config'], verbose)

@cli.command()
@click.argument('input_file', type=Path)
@click.option('--type', type=click.Choice(['pdf', 'image', 'auto']), default='auto')
@click.option('--beverage', type=click.Choice(['wine', 'whiskey', 'auto']), default='auto')
@click.option('--output', '-o', type=Path, help='Output JSON file')
@click.option('--review/--no-review', default=True, help='Interactive review')
@click.pass_context
def extract(ctx, input_file, type, beverage, output, review):
    """
    Extract bottle data from PDF or image.

    Examples:
      reserve-automation extract sommelier_list.pdf
      reserve-automation extract label.jpg --type image --beverage whiskey
      reserve-automation extract scan.pdf --output bottles.json --no-review
    """
    config = ctx.obj['config']

    console.print(f"[bold]Processing {input_file.name}...[/bold]")

    # Run extraction pipeline
    result = asyncio.run(
        extraction_pipeline(
            input_file=input_file,
            input_type=type,
            beverage_type=beverage,
            config=config
        )
    )

    # Display results
    _display_extraction_results(result)

    # Interactive review if requested
    if review and result.needs_review:
        console.print("\n[yellow]⚠ Some bottles need review:[/yellow]")
        reviewed = _interactive_review(result.needs_review)

        # Merge back
        result.bottles = result.high_confidence + reviewed
        result.needs_review = []
        result.high_confidence_count = len(result.bottles)
        result.needs_review_count = 0

    # Save output
    if output:
        output.write_text(result.json(indent=2))
        console.print(f"\n[green]✓ Saved to {output}[/green]")

    return result

@cli.command()
@click.argument('extraction_json', type=Path)
@click.option('--vault', type=Path, help='Vault path (overrides config)')
@click.option('--branch', default='tastings-backup', help='Git branch')
@click.option('--commit/--no-commit', default=False, help='Auto-commit to git')
@click.option('--dry-run', is_flag=True, help='Show what would be created')
@click.pass_context
def generate(ctx, extraction_json, vault, branch, commit, dry_run):
    """
    Generate Obsidian files from extraction results.

    Examples:
      reserve-automation generate bottles.json --commit
      reserve-automation generate bottles.json --dry-run
    """
    config = ctx.obj['config']
    vault_path = vault or config.vault_path

    if not vault_path:
        console.print("[red]Error: Vault path not configured[/red]")
        console.print("Set in config/user.yaml or use --vault")
        return

    # Load extraction result
    result = ExtractionResult.parse_file(extraction_json)

    console.print(f"[bold]Generating {len(result.bottles)} bottles...[/bold]\n")

    # Generate files
    generator = ObsidianGenerator(
        vault_path=vault_path,
        template_dir=config.templates_dir
    )

    created_files = []
    for bottle in track(result.bottles, description="Creating files"):
        obsidian_file = generator.generate_bottle_file(bottle)

        if not dry_run:
            obsidian_file.write()
            console.print(f"[green]✓[/green] {obsidian_file.file_path}")
            created_files.append(obsidian_file)
        else:
            console.print(f"[dim]Would create:[/dim] {obsidian_file.file_path}")

    # Git operations
    if commit and not dry_run:
        git_ops = GitOperations(vault_path)
        git_ops.commit_bottles(result.bottles, branch)
        console.print(f"\n[green]✓ Committed to git ({branch})[/green]")

@cli.command()
@click.argument('input_file', type=Path)
@click.option('--output-dir', type=Path, help='Output directory for results')
@click.option('--commit/--no-commit', default=False, help='Auto-commit to git')
@click.pass_context
def pipeline(ctx, input_file, output_dir, commit):
    """
    Run full pipeline: extract → generate → commit.

    This is a convenience command that combines:
      1. extract (with review)
      2. generate
      3. git commit (if --commit)

    Example:
      reserve-automation pipeline sommelier_list.pdf --commit
    """
    config = ctx.obj['config']

    console.print("[bold]🚀 Running full pipeline[/bold]\n")

    # Step 1: Extract
    console.print("[bold]Step 1: Extraction[/bold]")
    ctx.invoke(
        extract,
        input_file=input_file,
        type='auto',
        beverage='auto',
        output=output_dir / 'extraction.json' if output_dir else None,
        review=True
    )

    # Step 2: Generate
    console.print("\n[bold]Step 2: Generation[/bold]")
    ctx.invoke(
        generate,
        extraction_json=output_dir / 'extraction.json',
        commit=commit
    )

    console.print("\n[green]✓ Pipeline complete![/green]")

@cli.group()
def config_group():
    """Configuration management"""
    pass

@config_group.command('show')
@click.pass_context
def config_show(ctx):
    """Show current configuration"""
    config = ctx.obj['config']
    console.print(config.json(indent=2))

@config_group.command('init')
def config_init():
    """Initialize user configuration"""
    user_config = Path("config/user.yaml")

    if user_config.exists():
        console.print("[yellow]user.yaml already exists[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    # Copy example
    import shutil
    shutil.copy("config/user.yaml.example", user_config)

    console.print("[green]✓ Created config/user.yaml[/green]")
    console.print("Edit this file to customize settings")

@cli.group()
def llm():
    """LLM diagnostics and testing"""
    pass

@llm.command('test')
@click.option('--provider', help='Provider name to test')
@click.pass_context
def llm_test(ctx, provider):
    """Test LLM connection"""
    config = ctx.obj['config']
    gateway = LLMGateway(config.llm)

    if provider:
        providers = {provider: gateway.providers[provider]}
    else:
        providers = gateway.providers

    console.print("[bold]Testing LLM providers...[/bold]\n")

    for name, prov in providers.items():
        console.print(f"Testing {name}... ", end="")

        if asyncio.run(prov.health_check()):
            console.print("[green]✓ OK[/green]")
        else:
            console.print("[red]✗ FAILED[/red]")

def _display_extraction_results(result: ExtractionResult):
    """Display extraction results in formatted table"""
    table = Table(title=f"Extraction Results ({result.source_file})")

    table.add_column("Producer", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Year")
    table.add_column("Type")
    table.add_column("Confidence", justify="right")

    for bottle in result.bottles:
        confidence_color = "green" if bottle.confidence >= 0.8 else "yellow"

        table.add_row(
            bottle.producer,
            bottle.name,
            str(bottle.year) if bottle.year else "-",
            bottle.type,
            f"[{confidence_color}]{bottle.confidence:.0%}[/{confidence_color}]"
        )

    console.print(table)

    # Summary
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Total: {result.total_extracted}")
    console.print(f"  High confidence: [green]{result.high_confidence_count}[/green]")
    console.print(f"  Needs review: [yellow]{result.needs_review_count}[/yellow]")
    console.print(f"  Processing time: {result.processing_time_seconds:.2f}s")

def _interactive_review(bottles: List[BottleMetadata]) -> List[BottleMetadata]:
    """Interactive review of low-confidence bottles"""
    reviewed = []

    for i, bottle in enumerate(bottles, 1):
        console.print(f"\n[bold]Bottle {i}/{len(bottles)}[/bold]")
        console.print(f"Producer: {bottle.producer}")
        console.print(f"Name: {bottle.name}")
        console.print(f"Year: {bottle.year or '(not set)'}")
        console.print(f"Confidence: {bottle.confidence:.0%}")

        action = click.prompt(
            "Action",
            type=click.Choice(['accept', 'edit', 'skip']),
            default='accept'
        )

        if action == 'accept':
            reviewed.append(bottle)
        elif action == 'edit':
            # Edit fields
            bottle.producer = click.prompt("Producer", default=bottle.producer)
            bottle.name = click.prompt("Name", default=bottle.name)
            year_str = click.prompt("Year", default=str(bottle.year) if bottle.year else "")
            bottle.year = int(year_str) if year_str else None

            bottle.confidence = 1.0  # User-verified
            reviewed.append(bottle)
        # skip: don't add to reviewed

    return reviewed

if __name__ == '__main__':
    cli()
```

---

## Testing Strategy

### Test Structure

```
tests/
├── unit/
│   ├── test_parsers.py
│   ├── test_extractors.py
│   ├── test_llm_gateway.py
│   ├── test_generators.py
│   └── test_config.py
├── integration/
│   ├── test_extraction_pipeline.py
│   ├── test_obsidian_generation.py
│   └── test_git_operations.py
├── fixtures/
│   ├── sample_sommelier_list.pdf
│   ├── sample_wine_label.jpg
│   ├── sample_whiskey_label.jpg
│   └── expected_outputs/
│       ├── extraction_wine.json
│       └── extraction_whiskey.json
└── conftest.py  # Pytest configuration
```

### Key Tests

```python
# tests/unit/test_parsers.py
import pytest
from pathlib import Path
from reserve_automation.parsers import PDFParser, ImageParser

@pytest.fixture
def sample_pdf():
    return Path("tests/fixtures/sample_sommelier_list.pdf")

@pytest.mark.asyncio
async def test_pdf_parser(sample_pdf):
    """Test PDF parsing extracts text"""
    parser = PDFParser()
    result = await parser.parse(sample_pdf)

    assert result.raw_text
    assert result.source_type == 'pdf'
    assert len(result.raw_text) > 100  # Should have content

# tests/unit/test_extractors.py
@pytest.mark.asyncio
async def test_bottle_extraction(mock_llm_gateway):
    """Test bottle extraction from parsed text"""
    extractor = BottleExtractor(mock_llm_gateway)

    parser_result = ParserResult(
        raw_text="Alvaro Palacios Finca Dofí Priorat 2016 - $65",
        images=[],
        metadata={},
        source_type='pdf'
    )

    bottles = await extractor.extract(parser_result, beverage_type='wine')

    assert len(bottles) == 1
    assert bottles[0].producer == "Alvaro Palacios"
    assert bottles[0].name == "Finca Dofí Priorat"
    assert bottles[0].year == 2016
    assert bottles[0].price == 65.0

# tests/integration/test_extraction_pipeline.py
@pytest.mark.asyncio
async def test_full_extraction_pipeline():
    """Test complete extraction: parse → extract → validate"""
    input_file = Path("tests/fixtures/sample_sommelier_list.pdf")

    result = await extraction_pipeline(
        input_file=input_file,
        input_type='auto',
        beverage_type='auto',
        config=test_config
    )

    assert result.total_extracted > 0
    assert result.high_confidence_count > 0
    assert all(b.confidence >= 0 for b in result.bottles)
```

### Mock LLM for Testing

```python
# tests/conftest.py
import pytest
from reserve_automation.llm.gateway import LLMGateway, LLMResponse

@pytest.fixture
def mock_llm_gateway():
    """Mock LLM gateway for testing without API calls"""

    class MockLLMGateway:
        async def complete(self, task_type, prompt, **kwargs):
            # Return canned responses based on task type
            if task_type == 'extraction':
                return LLMResponse(
                    content='{"bottles": [{"producer": "Test", "name": "Wine", "type": "wine"}]}',
                    provider='mock',
                    model='mock-model',
                    tokens_used=100,
                    latency_ms=50
                )

            return LLMResponse(
                content='Mock response',
                provider='mock',
                model='mock-model',
                tokens_used=50,
                latency_ms=25
            )

    return MockLLMGateway()
```

---

## Development Roadmap

### Phase 1.1: Foundation (Weeks 1-2) ✅ Complete

**Deliverables:**
- [x] Project structure and scaffolding
- [x] Configuration system (YAML loading, validation)
- [x] Data models (Pydantic schemas)
- [x] Logging setup
- [x] Basic CLI skeleton

**Testing:**
- [x] Config loading tests
- [x] Model validation tests

### Phase 1.2: LLM Gateway (Week 3) ✅ Complete

**Deliverables:**
- [x] Base LLM provider interface
- [x] LM Studio provider implementation
- [x] Anthropic provider (fallback)
- [x] Task routing system
- [x] Health check utilities

**Testing:**
- [x] Mock provider tests
- [x] Routing logic tests
- [x] Integration test with real LM Studio

### Phase 1.3: Parsers (Week 4) ✅ Complete

**Deliverables:**
- [x] PDF parser (pdfplumber + OCR fallback)
- [x] Image parser (tesseract)
- [x] Auto-detection logic
- [x] Parser result models

**Testing:**
- [x] Unit tests with fixture files
- [x] OCR quality tests
- [x] Edge case handling (corrupted files, etc.)

### Phase 1.4: Extraction Pipeline (Weeks 5-6) ✅ Complete

**Deliverables:**
- [x] Bottle extractor with LLM integration
- [x] Confidence scoring algorithm
- [x] Extraction prompts (wine & whiskey)
- [x] Validation and error handling

**Testing:**
- [x] Extraction accuracy tests (12/12 bottles extracted successfully)
- [x] Confidence scoring tests
- [x] End-to-end pipeline tests

### Phase 1.5: Obsidian Generation (Week 7) ✅ Complete

**Deliverables:**
- [x] Jinja2 templates (wine & whiskey)
- [x] Obsidian file generator
- [ ] Git operations wrapper (partial - manual commit working)
- [x] Filename sanitization

**Testing:**
- [x] Template rendering tests (19 unit tests passing)
- [x] File creation tests
- [ ] Git commit tests (with test repo)

### Phase 1.6: CLI & Polish (Week 8)

**Deliverables:**
- [ ] All CLI commands implemented
- [ ] Interactive review UI (Rich)
- [ ] Progress indicators
- [ ] Error messages and help text
- [ ] Documentation

**Testing:**
- [ ] CLI integration tests
- [ ] User acceptance testing

### Phase 1.7: Release (Week 9)

**Deliverables:**
- [ ] README with setup instructions
- [ ] Example config files
- [ ] Sample input fixtures
- [ ] Installation script
- [ ] Docker image (optional)

---

## Future Phases

### Phase 2: Web Research & Enrichment

**Features:**
- Web scraping for missing metadata
- Label image finding (Google, wine databases)
- Image downloading and cropping (vision models)
- Metadata validation against online sources

**New Components:**
- `enrichers/web_search.py`
- `enrichers/image_finder.py`
- `enrichers/vision_cropper.py`

### Phase 3: API Server

**Features:**
- FastAPI REST endpoints
- File upload handling
- Job queue (Celery + Redis)
- SQLite database for job tracking
- Authentication (JWT)

**Infrastructure:**
- Docker Compose stack
- Proxmox LXC deployment
- Traefik reverse proxy

### Phase 4: Web Frontend

**Features:**
- Drag-drop upload interface
- Real-time progress tracking
- Batch operations
- Bottle management UI
- Search and filtering

**Tech Stack:**
- Svelte or React
- WebSocket for real-time updates
- Chart.js for statistics

### Phase 5: Tasting Sessions

**Features:**
- Multi-user tasting sessions
- Real-time scoring
- Aggregated results
- Blind tasting mode
- Session reports

**New Models:**
- TastingSession
- TastingScore
- SessionParticipant

---

## Appendix

### Dependencies (requirements.txt)

```txt
# Core
python>=3.11
pydantic>=2.0
click>=8.1
pyyaml>=6.0

# LLM
httpx>=0.27
anthropic>=0.20
openai>=1.0

# Parsing
pdfplumber>=0.10
pytesseract>=0.3
Pillow>=10.0
pdf2image>=1.16

# Generation
Jinja2>=3.1
GitPython>=3.1

# CLI/UI
rich>=13.0

# Testing
pytest>=7.4
pytest-asyncio>=0.21
pytest-mock>=3.12

# Future phases
fastapi>=0.110
celery>=5.3
redis>=5.0
sqlalchemy>=2.0
```

### Environment Variables

```bash
# LLM API Keys (optional)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Paths (override config)
RESERVE_VAULT_PATH=/path/to/the-reserve
RESERVE_CONFIG_DIR=/path/to/config

# LM Studio
LM_STUDIO_BASE_URL=http://192.168.1.100:1234/v1
```

### Deployment Checklist

**Local Development:**
- [ ] Python 3.11+ installed
- [ ] LM Studio running with models loaded
- [ ] the-reserve repo cloned and on tastings-backup branch
- [ ] Config files created (user.yaml)
- [ ] Dependencies installed (`pip install -e .`)

**Proxmox Deployment (Future):**
- [ ] LXC container created
- [ ] Docker and Docker Compose installed
- [ ] Network configured (access to LM Studio on PC)
- [ ] SSL certificates (Let's Encrypt)
- [ ] Backup strategy for SQLite database

---

**End of Design Document**

*Last Updated: 2025-12-06*
*Author: Ben Smith (with Claude Sonnet 4.5)*
