# Image-Based Bottle Ingestion

## Overview

The `add-from-image` command allows you to add bottles to your Obsidian vault by simply taking a photo of the label. The system uses vision LLM to extract metadata, enriches it with web search, and automatically saves the label image.

## Quick Start

```bash
# Basic usage - take a photo and process it
reserve-automation add-from-image photo.jpg

# With type hint for better extraction
reserve-automation add-from-image label.png --beverage wine

# Specify year if not visible on label
reserve-automation add-from-image bottle.jpg --year 2019

# Include price information
reserve-automation add-from-image image.jpg --price 45.99

# Preview extraction without creating files
reserve-automation add-from-image test.jpg --dry-run
```

## Workflow

### 1. Vision Extraction

The system reads the label using vision LLM and extracts:
- **Producer/Winery name**
- **Wine/Whiskey name**
- **Vintage/Year** (if visible)
- **Type** (red wine, bourbon, etc.)
- **Alcohol percentage/proof** (if visible)
- **Region/Appellation** (if visible)
- **Grape variety or mash bill** (if visible)

### 2. Missing Year Handling

If the year/vintage is not visible on the label:
- The system will prompt you to enter it
- You can skip if year is not applicable (e.g., NV wines)
- Or provide it via `--year` flag upfront

### 3. Web Search Enrichment

After extraction, the system automatically:
- Searches multiple sources (producer websites, wine databases, retailers)
- Verifies extracted information
- Fills in missing details (country, region precision, variety details)
- Cross-references multiple sources for accuracy

### 4. Label Saving

The provided image is:
- Automatically saved to `bottle_folder/labels/label.jpg`
- Converted to JPEG if needed (handles PNG, RGBA, etc.)
- Linked in the Obsidian note's `Label` field
- Ready for display in collection views

### 5. Obsidian Note Creation

Final step:
- Generates properly formatted markdown file
- Includes all enriched metadata
- Saves to appropriate vault location
- Ready to edit/enhance with tasting notes

## Best Practices

### Taking Photos

**For best extraction results:**
- **Lighting**: Ensure good, even lighting without glare
- **Focus**: Label should be sharp and in focus
- **Angle**: Straight-on shot works best (avoid extreme angles)
- **Coverage**: Capture entire label including vintage if shown
- **Resolution**: Higher resolution helps OCR accuracy

**What to photograph:**
- Front label (main label with name/producer)
- Vintage year if visible anywhere on bottle
- Back label if it contains key information

### Handling Edge Cases

**Year not visible:**
```bash
# If you know the year beforehand
reserve-automation add-from-image label.jpg --year 2020

# Otherwise, you'll be prompted to enter it
```

**Ambiguous beverage type:**
```bash
# Provide a hint to improve extraction
reserve-automation add-from-image label.jpg --beverage whiskey
```

**Testing before committing:**
```bash
# Always available to preview
reserve-automation add-from-image label.jpg --dry-run
```

## Example Sessions

### Example 1: Wine with Visible Year

```bash
$ reserve-automation add-from-image chateau-label.jpg

Adding bottle from image: chateau-label.jpg

╭─── Extracted from Label ───╮
│ Producer: Chateau Margaux  │
│ Name: Grand Vin            │
│ Year: 2015                 │
│ Type: Red wine             │
│ Region: Margaux            │
│ Variety: (will enrich)     │
│ Confidence: high           │
╰────────────────────────────╯

Enriching metadata with web search...

✓ Found 2 additional details:
  • variety: Cabernet Sauvignon blend (89% CS, 7% Merlot, 3% Cab Franc, 1% Petit Verdot)
  • country: France

╭────── Final Metadata ──────╮
│ Producer: Chateau Margaux  │
│ Name: Grand Vin            │
│ Year: 2015                 │
│ Type: Red wine             │
│ Country: France            │
│ Region: Margaux AOC        │
│ Variety: Cabernet Sauv... │
│ Price: $0.00               │
╰────────────────────────────╯

Generating Obsidian note...
✓ Created: Cellar/1_Wines/Chateau Margaux - Grand Vin - 2015/Chateau Margaux - Grand Vin - 2015.md
✓ Saved label: .../labels/label.jpg
✓ Updated Label field in note

✓ Bottle added successfully!
```

### Example 2: Whiskey without Visible Year

```bash
$ reserve-automation add-from-image stagg-jr.jpg --beverage whiskey

Adding bottle from image: stagg-jr.jpg

╭──── Extracted from Label ────╮
│ Producer: Buffalo Trace       │
│ Name: Stagg Jr Batch 24D      │
│ Year: MISSING                 │
│ Type: Bourbon                 │
│ Region: (will enrich)         │
│ Variety: (will enrich)        │
│ Confidence: high              │
╰───────────────────────────────╯

⚠ Year/vintage not visible on label
Enter vintage/year (or press Enter to skip): 2024

Enriching metadata with web search...

✓ Found 4 additional details:
  • country: USA
  • region: Kentucky
  • variety: Kentucky Straight Bourbon
  • mash_bill: Buffalo Trace Mash Bill #1

╭────── Final Metadata ──────╮
│ Producer: Buffalo Trace    │
│ Name: Stagg Jr Batch 24D   │
│ Year: 2024                 │
│ Type: Bourbon              │
│ Country: USA               │
│ Region: Kentucky           │
│ Variety: Kentucky Str...   │
│ Price: $0.00               │
╰────────────────────────────╯

✓ Bottle added successfully!
```

### Example 3: Dry Run Mode

```bash
$ reserve-automation add-from-image test.jpg --dry-run

Adding bottle from image: test.jpg

╭─── Extracted from Label ───╮
│ Producer: Bonanza          │
│ Name: The Vinekeeper       │
│ Year: 2024                 │
│ Type: Red wine             │
│ Region: Napa Valley        │
│ Variety: Cabernet Sauv...  │
│ Confidence: high           │
╰────────────────────────────╯

Enriching metadata with web search...
✓ Metadata verified

╭────── Final Metadata ──────╮
│ Producer: Bonanza          │
│ Name: The Vinekeeper       │
│ Year: 2024                 │
│ Type: Red wine             │
│ Country: USA               │
│ Region: Napa Valley        │
│ Variety: Cabernet Sauv...  │
│ Price: $0.00               │
╰────────────────────────────╯

DRY RUN - No files created
```

## Integration with Existing Features

### Automatic Enrichment

The `add-from-image` command automatically uses:
- **Vision LLM** (`ocr` task type) for label reading
- **Web search tools** (`metadata_enrichment` task type) for verification
- Same enrichment logic as `verify-metadata` command

### Label Quality

Unlike `find-labels` which searches and scores images:
- Your provided image is always used as-is
- No quality scoring needed (you chose the photo)
- No need for web search to find label images
- Faster workflow for bottles you have physically

### Obsidian Integration

Generated files use:
- Same templates as other ingestion methods
- Same FileClass definitions (Wine.md, Whiskey.md)
- Same folder structure
- Same Label field integration

## Command Reference

```bash
reserve-automation add-from-image IMAGE_PATH [OPTIONS]
```

### Arguments

- `IMAGE_PATH` - Path to bottle/label photo (required)

### Options

- `--beverage [wine|whiskey]` - Beverage type hint for better extraction
- `--year INT` - Vintage/year if not visible on label
- `--price FLOAT` - Purchase price to record
- `--dry-run` - Preview extraction without creating files

### Exit Codes

- `0` - Success
- `1` - Extraction or generation failed
- `130` - Interrupted by user (Ctrl+C)

## Troubleshooting

### "Extraction failed: No JSON found"

**Cause:** Vision LLM couldn't parse the label

**Solutions:**
- Ensure label is clearly visible and in focus
- Try better lighting or different angle
- Provide beverage type hint: `--beverage wine`
- Check if image file is corrupted

### "Year/vintage not visible on label"

**Normal behavior** - the system prompts you to enter it

**Solutions:**
- Enter the year when prompted
- Or provide upfront: `--year 2020`
- Or press Enter to skip (for NV wines)

### "Failed to generate Obsidian file"

**Cause:** Issue with vault path or templates

**Solutions:**
- Verify vault path in config: `config/user.yaml`
- Ensure templates exist in `templates/` directory
- Check vault folder permissions

### Incorrect Metadata Extracted

**Cause:** OCR misread label or ambiguous text

**Solutions:**
- Try `--dry-run` first to preview
- Edit the generated Obsidian note manually
- Or run `verify-metadata` after creation to re-check

## Performance

**Typical processing time:** 10-30 seconds per bottle
- Vision extraction: 3-5 seconds
- Web enrichment: 5-20 seconds (depending on searches)
- File generation: <1 second
- Image processing: <1 second

**Token usage:** 800-1500 tokens
- Vision LLM: 200-500 tokens (label reading)
- Web enrichment: 500-1000 tokens (metadata verification)

## Future Enhancements

Potential improvements:
- Batch mode for multiple images
- Auto-crop to label region before saving
- Support for back labels (additional extraction)
- Price extraction from receipts
- Mobile app integration for instant capture
