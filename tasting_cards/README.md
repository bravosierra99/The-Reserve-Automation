# Tasting Card Templates and Examples

This directory contains tasting card templates and example photos for developing the tasting card extraction feature.

## Directory Structure

- **templates/** - Official tasting card templates (PDF/images)
  - Place blank tasting card templates here
  - Examples: AWS wine tasting chart, bourbon tasting sheets, etc.

- **examples/** - Example photos of filled-out tasting cards
  - Photos of actual tasting cards you've filled out
  - Used for testing the extraction logic
  - Can include multiple cards per image

- **docs/** - Documentation and reference materials
  - Notes about the tasting card formats
  - Field descriptions
  - Scoring systems explanations

## Templates to Add

### Wine Tasting Cards
- [ ] AWS (American Wine Society) 20-point tasting chart
  - Source: https://americanwinesociety.org/
  - Fields: Appearance, Aroma, Taste, Aftertaste, Overall
  - Total: 20 points max

### Whiskey/Bourbon Tasting Cards
- [ ] Standard bourbon tasting sheet
  - Fields: Nose, Palate, Finish, Overall
  - Total: 40 points (10 per category)

## Next Steps

1. Download the AWS wine tasting chart PDF and place in `templates/`
2. Find/download a bourbon tasting sheet and place in `templates/`
3. Take photos of filled-out tasting cards and place in `examples/`
4. Claude will analyze the templates to design the extraction logic
