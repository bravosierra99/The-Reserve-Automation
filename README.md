# Automation Tools for The Reserve

Automation tools for ingesting bottles and processing label images for The Reserve spirits collection.

## Status

🚧 **Under Development** - This project is just getting started.

## Planned Features

### Bottle Ingestion Pipeline
- **Input Sources**:
  - Sommelier lists (PDF/paper scans)
  - Bottle photos (label text extraction)
  - Manual entry (CLI/form)

- **Research Agent**:
  - Web scraping for bottle metadata
  - Confidence scoring for matches
  - Interactive validation when uncertain

- **Image Processing**:
  - Find and download official label images
  - ML-based label cropping (using local vision models via LM Studio)
  - Optimize for Obsidian display

- **Obsidian Generation**:
  - Create bottle markdown files
  - Save labels to correct location
  - Integrate with git workflow

### Tech Stack (Planned)

- **Python** for orchestration
- **LM Studio API** for local vision models (label detection, text extraction)
- **Requests + BeautifulSoup** for web scraping
- **PIL/OpenCV** for image manipulation
- **Click** for CLI

## Directory Structure (Future)

```
automation/
├── README.md
├── requirements.txt
├── src/
│   ├── ingest.py           # Main entry point
│   ├── parsers/
│   │   ├── pdf.py          # Parse sommelier lists
│   │   └── photo.py        # Extract from bottle photos
│   ├── research/
│   │   └── agent.py        # Web research for bottle data
│   ├── images/
│   │   ├── finder.py       # Find label images online
│   │   └── processor.py    # Crop and optimize
│   └── obsidian/
│       └── generator.py    # Create markdown files
├── config/
│   └── config.yaml         # User configuration
└── tests/
```

## Coming Soon

This directory will be initialized as a separate git repository once development begins.

---

**Related Project**: [the-reserve](../the-reserve/) - The Obsidian vault this tool populates
