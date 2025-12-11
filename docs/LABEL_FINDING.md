# Automatic Label Finding & Processing

## Overview

The `find-labels` command automatically discovers, scores, crops, and saves bottle label images for bottles already in your Obsidian vault. It combines web search, vision LLM quality assessment, intelligent cropping, and seamless Obsidian integration.

## Quick Start

```bash
# Automatic mode - finds, scores, crops, and saves automatically
reserve-automation find-labels --yes --missing-only

# Interactive mode - choose which images to use
reserve-automation find-labels --missing-only

# Test on a few bottles first
reserve-automation find-labels --limit 5 --dry-run

# Only process whiskeys
reserve-automation find-labels --beverage whiskey --missing-only
```

## Workflow

### 1. Web Search for Label Images

The system uses LLM with web search tools to find label images from:
- **Official sources**: Distillery/winery websites
- **Retailers**: Total Wine, Binny's, Wine.com, etc.
- **Databases**: Vivino, Wine-Searcher, Whisky Advocate
- **Review sites**: Blog posts, reviews, community photos

### 2. Quality Scoring (Automatic Mode Only)

When using `--yes` flag, the vision LLM scores each image on a 0-10 scale:

**Quality Scale:**
- **10**: Perfect label shot - clean, straight-on, full label visible, no glare
- **9**: Excellent - minor imperfections but label is clear
- **8**: Very good - slight angle or lighting issues but perfectly usable
- **7**: Good - acceptable quality with some issues (threshold for automatic use)
- **6**: Fair - label visible but lifestyle/context shot
- **5**: Marginal - label partially visible
- **0-4**: Poor quality or wrong bottle

**Automatic Selection:** Only images scoring ≥ 7.0 are used automatically

### 3. Intelligent Cropping

After downloading, the vision LLM:
- Detects the label bounding box coordinates
- Adds 3% padding on all sides to ensure no edge cutoff
- Validates bounds are within image dimensions
- Crops the image to show just the label

**Benefits:**
- Removes lifestyle/pour shots backgrounds
- Focuses on the label itself
- Consistent aspect ratios across your collection
- Smaller file sizes

### 4. Image Processing

The system automatically:
- Converts PNG/RGBA images to RGB mode
- Saves as JPEG with 95% quality
- Optimizes file size
- Overwrites the original with the cropped version

### 5. Obsidian Integration

For each bottle with a new label:
- Updates the `Label` field in frontmatter
- Sets value to `labels/label.jpg` (relative path)
- Preserves all other frontmatter fields
- Makes the label immediately visible in collection views

### 6. Review Log

Bottles that need manual attention are logged to `label_review.log`:
- No quality images found
- Download failures
- Cropping failures
- Frontmatter update issues

## Usage Modes

### Automatic Mode (Recommended)

Use `--yes` flag for fully automated operation:

```bash
reserve-automation find-labels --yes --missing-only
```

**What happens:**
1. Searches for each bottle without a label
2. Scores all found images
3. Auto-selects highest quality image (≥ 7.0)
4. Downloads image
5. Detects and crops to label bounds
6. Updates Obsidian frontmatter
7. Logs any issues to `label_review.log`

**Best for:** Batch processing many bottles, hands-off operation

### Interactive Mode

Omit `--yes` flag for manual control:

```bash
reserve-automation find-labels --missing-only
```

**What happens:**
1. Searches for each bottle
2. Displays all found images
3. You choose which image to download
4. Downloads your selection
5. No scoring or cropping (saves original)
6. No automatic Obsidian updates

**Best for:** Careful selection, reviewing sources, specific image preferences

### Dry Run Mode

Preview what will happen without making changes:

```bash
reserve-automation find-labels --dry-run
```

Shows the search query that would be used for each bottle.

## Command Reference

```bash
reserve-automation find-labels [OPTIONS]
```

### Options

- `--beverage [wine|whiskey|all]` - Filter by beverage type (default: all)
- `--missing-only` - Only process bottles without existing labels (recommended)
- `--limit INT` - Limit to first N bottles (useful for testing)
- `--dry-run` - Preview queries without downloading
- `--yes`, `-y` - Automatic mode (skip confirmations, enable scoring & cropping)

### Exit Codes

- `0` - Success
- `1` - Error occurred
- `130` - Interrupted by user (Ctrl+C)

## Examples

### Example 1: Automatic Mode (Full Collection)

```bash
$ reserve-automation find-labels --yes --missing-only

Finding Bottle Label Images

Found 50 bottles in vault
Filtering to 23 bottles missing labels

Processing 23 bottles

[1/23] Chateau Margaux - Grand Vin
  Searching web for label images...
  ✓ Found 3 quality images (>= 7.0)
  Selected: https://example.com/margaux.jpg (score: 8.5/10)
  Source: chateaumargaux.com

  ✓ Downloaded to labels/label.jpg
  Detecting label bounds...
  Cropping to label...
  ✓ Cropped label image
  Updating Obsidian metadata...
  ✓ Updated Label field in Obsidian

[2/23] Buffalo Trace - Stagg Jr
  Searching web for label images...
  ⚠ No images found

...

╭─────── Summary ───────╮
│ Processed: 23 bottles │
│ Found: 45 images      │
│ Downloaded: 20 images │
│ Cropped: 18 images    │
│ Updated: 20 in Obs... │
│ Needs review: 3 bot...│
╰───────────────────────╯

⚠ 3 bottles need manual review
See /path/to/label_review.log for details
```

### Example 2: Interactive Mode

```bash
$ reserve-automation find-labels --missing-only

Finding Bottle Label Images

Found 50 bottles in vault
Filtering to 23 bottles missing labels

⚠ Label finding requires internet access and may take a while
Tip: Use Ctrl+C to skip to next bottle

Continue? [y/N]: y

[1/23] Chateau Margaux - Grand Vin
  Searching web for label images...
  ✓ Found 4 images

  Select an image to download:
    [1] https://chateaumargaux.com/images/2015-grand-vin.jpg
        Source: chateaumargaux.com - Official label image from winery
    [2] https://totalwine.com/media/margaux-2015.jpg
        Source: totalwine.com - Product photo
    [3] https://vivino.com/wines/margaux.jpg
        Source: vivino.com - User submitted photo
    [0] Skip this bottle

  Enter choice: 1

  Downloading from chateaumargaux.com...
  ✓ Downloaded to labels/label.jpg

[2/23] Buffalo Trace - Stagg Jr
  Searching web for label images...
  ⚠ No images found

...

╭─────── Summary ───────╮
│ Processed: 23 bottles │
│ Found: 45 images      │
│ Downloaded: 15 images │
╰───────────────────────╯
```

### Example 3: Test Run

```bash
$ reserve-automation find-labels --limit 3 --dry-run

Finding Bottle Label Images

Found 50 bottles in vault
Limited to first 3 bottles

DRY RUN: Showing search queries only

• Chateau Margaux Grand Vin → Chateau Margaux Grand Vin 2015 wine bottle label
• Buffalo Trace Stagg Jr → Buffalo Trace Stagg Jr 2024 whiskey bottle label
• Bonanza The Vinekeeper → Bonanza The Vinekeeper 2024 wine bottle label
```

## Review Log

When running in automatic mode (`--yes`), bottles needing manual attention are logged:

### Example: `label_review.log`

```
# Bottles Needing Manual Review
# Generated: 2025-12-10 14:30:45

- Buffalo Trace - Stagg Jr - 2024
  Issue: no_quality_images
  Details: No images scored >= 7.0

- Bonanza - The Vinekeeper - 2024
  Issue: crop_failed
  Details: Bounds: (120, 350, 480, 820)

- Chateau Lafite - Rothschild - 2010
  Issue: frontmatter_failed
  Details: /path/to/Cellar/1_Wines/Chateau Lafite - Rothschild - 2010/Chateau Lafite - Rothschild - 2010.md
```

### Issue Types

- **no_images** - Web search found no images
- **no_quality_images** - All images scored below 7.0
- **download_failed** - HTTP request failed
- **detection_failed** - Vision LLM couldn't detect label bounds
- **crop_failed** - PIL cropping operation failed
- **frontmatter_failed** - YAML parsing/writing failed
- **file_not_found** - Bottle markdown file missing
- **processing_error** - Unexpected error occurred

## Integration with Other Features

### Vault Structure

Labels are saved to maintain proper vault structure:

```
Cellar/
├── 1_Wines/
│   └── Producer - Name - Year/
│       ├── Producer - Name - Year.md  ← Label field updated here
│       └── labels/
│           └── label.jpg  ← Image saved here
```

### Obsidian Label Field

The frontmatter `Label` field is updated:

```yaml
---
Winemaker: Chateau Margaux
WineName: Grand Vin
Vintage: 2015
Label: labels/label.jpg  ← Added/updated automatically
---
```

This makes labels appear in:
- Collection card views (`0_Collection/Cards.md`)
- Shopping lists
- Any other views using the Label field

### Metadata Enrichment

`find-labels` complements other commands:

1. **add-from-image** - You provide the photo, generates metadata
2. **verify-metadata** - Verifies metadata accuracy with web sources
3. **find-labels** - Finds and processes labels for existing bottles

### FileClass Compatibility

Works with both Wine and Whiskey FileClass definitions:
- Automatically detects bottle folder structure
- Updates the correct markdown file
- Preserves all existing frontmatter fields

## Performance

### Typical Processing Time

**Per bottle (automatic mode):** 30-60 seconds
- Web search: 10-30s
- Image download: 2-5s
- Quality scoring: 5-10s (per image, may score 2-5 images)
- Bounding box detection: 5-10s
- Cropping: <1s
- Frontmatter update: <1s

**Per bottle (interactive mode):** 15-45 seconds
- Web search: 10-30s
- Image download: 2-5s
- User selection: variable

### Token Usage

**Automatic mode (per bottle):**
- Web search: 500-1500 tokens (LLM + tools)
- Quality scoring: 100-200 tokens per image (vision LLM)
- Bounding box detection: 100-200 tokens (vision LLM)
- **Total:** 800-2500 tokens per bottle (depending on image count)

**Interactive mode (per bottle):**
- Web search: 500-1500 tokens
- **Total:** 500-1500 tokens per bottle

### Batch Processing

For 50 bottles (automatic mode):
- **Time:** 25-50 minutes
- **Tokens:** 40,000-125,000 tokens
- **Network:** ~100MB download (varies by image sizes)

## Troubleshooting

### "No images found"

**Cause:** Web search didn't find any label images

**Solutions:**
- Check spelling of producer/name in bottle metadata
- Verify bottle year is correct
- Try interactive mode and search manually
- Some small producers may not have online images

### "No quality images (score < 7.0)"

**Cause:** All found images were low quality (lifestyle shots, poor angles, etc.)

**Solutions:**
- Check review log for the bottle name
- Use interactive mode to see what was found
- Manually search and add image to `labels/` folder
- Edit bottle metadata if search query was incorrect

### "Crop failed"

**Cause:** Vision LLM detected bounds but PIL couldn't crop

**Solutions:**
- Image may be in unusual format
- Bounds may be malformed
- Manual fix: Re-download image and place in `labels/` folder
- The uncropped image is still saved and usable

### "Detection failed"

**Cause:** Vision LLM couldn't detect label bounding box

**Solutions:**
- Image may be too low resolution
- Label may be at extreme angle
- Multiple bottles in frame
- Manual fix: Crop image yourself or accept uncropped version

### "Frontmatter update failed"

**Cause:** YAML parsing/writing error in Obsidian file

**Solutions:**
- Check bottle markdown file for syntax errors
- Verify file permissions
- Ensure file exists in expected location
- Manual fix: Edit markdown file and add `Label: labels/label.jpg`

### Download Failures

**Cause:** HTTP errors, timeouts, blocked requests

**Solutions:**
- Check internet connection
- Some sites block automated requests
- Try interactive mode with different image selection
- Retry later if site is temporarily down

## Best Practices

### Initial Run

1. **Start small:** Use `--limit 5 --dry-run` to preview
2. **Test automatic mode:** `--limit 3 --yes` on a few bottles
3. **Review results:** Check labels in Obsidian, review `label_review.log`
4. **Batch process:** `--yes --missing-only` for full collection

### Ongoing Maintenance

- Run after adding new bottles to vault
- Use `--missing-only` to only process new bottles
- Review log file periodically for manual fixes
- Re-run for bottles that failed if metadata was corrected

### Quality Control

- Automatic mode (7.0 threshold) works well for most bottles
- Interactive mode gives you full control
- Review cropped images in Obsidian card views
- Manually replace any unsatisfactory images

### Manual Overrides

To use your own image:
1. Place image in `bottle_folder/labels/label.jpg`
2. Edit bottle markdown to add `Label: labels/label.jpg`
3. System will skip bottles that already have labels

## Future Enhancements

Potential improvements:
- Configurable quality threshold (adjust 7.0 minimum)
- Multi-image support (front label, back label, etc.)
- Batch re-processing of existing labels
- Label deduplication across variants
- Mobile app integration for instant capture

## Related Documentation

- [IMAGE_INGESTION.md](IMAGE_INGESTION.md) - Add bottles from photos
- [README.md](../README.md) - Full project documentation
- [DESIGN.md](../DESIGN.md) - Technical architecture

---

**Built with:**
- Web search tools (DuckDuckGo, Brave, Mojeek, Yandex)
- Vision LLM (qwen/qwen3-vl-8b) for quality scoring and cropping
- Text LLM with tool calling for web search
- PIL for image processing
