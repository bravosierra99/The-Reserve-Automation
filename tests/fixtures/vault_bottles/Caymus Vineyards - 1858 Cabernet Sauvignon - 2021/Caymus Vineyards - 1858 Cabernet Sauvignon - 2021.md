---
fileClass: Wine
Name: Caymus Vineyards - 1858 Cabernet Sauvignon - 2021
Winemaker: Caymus Vineyards
WineName: 1858 Cabernet Sauvignon
Vintage: "2021"
Type: Red wine
Variety: Cabernet Sauvignon
Country-Region: United States - Napa Valley
Vineyard: Caymus Vineyards
Style: 
Price: "49.99"
PurchaseSource: 
PurchaseLink: 
Stars: --
ValueForMoney: 
Points: 
Inventory: 0
Buy: 0
ABV: 14.5
---

## Bottle Information

### Product Details


### Tasting Notes Summary

```dataviewjs
// Get the current bottle name
const currentBottle = dv.current().file.name;

// Get all tastings for this bottle (in subdirectory)
const tastings = dv.pages('"1_Wines/' + currentBottle + '"')
    .where(p => p.fileClass === "Wine Tasting")
    .sort(p => p.Date, 'desc');

if (tastings.length === 0) {
    dv.paragraph("No tastings recorded yet. [Add a tasting](#)");
} else {
    // Calculate per-taster averages
    const tasterStats = {};

    for (let tasting of tastings) {
        const taster = tasting.TasterName || "Unknown";
        if (!tasterStats[taster]) {
            tasterStats[taster] = {
                count: 0,
                appearance: 0,
                aroma: 0,
                taste: 0,
                aftertaste: 0,
                overall: 0,
                awsScore: 0,
                pt100: 0
            };
        }
        tasterStats[taster].count++;
        tasterStats[taster].appearance += tasting.Appearance || 0;
        tasterStats[taster].aroma += tasting.Aroma || 0;
        tasterStats[taster].taste += tasting.Taste || 0;
        tasterStats[taster].aftertaste += tasting.Aftertaste || 0;
        tasterStats[taster].overall += tasting.Overall || 0;
        tasterStats[taster].awsScore += tasting["AWS Score"] || 0;
        tasterStats[taster].pt100 += tasting["100pt Scale"] || 0;
    }

    // Display per-taster averages
    dv.header(3, "Average Scores by Taster (AWS 20-pt Scale)");
    const tasterRows = Object.entries(tasterStats).map(([taster, stats]) => [
        taster,
        stats.count,
        (stats.appearance / stats.count).toFixed(1),
        (stats.aroma / stats.count).toFixed(1),
        (stats.taste / stats.count).toFixed(1),
        (stats.aftertaste / stats.count).toFixed(1),
        (stats.overall / stats.count).toFixed(1),
        (stats.awsScore / stats.count).toFixed(1),
        (stats.pt100 / stats.count).toFixed(0)
    ]);
    dv.table(
        ["Taster", "Tastings", "Appear", "Aroma", "Taste", "Aftertaste", "Overall", "AWS", "100pt"],
        tasterRows
    );

    // Display all tastings
    dv.header(3, "All Tastings");
    const rows = tastings.map(p => [
        p.file.link,
        p.Date,
        p.TasterName,
        p.Appearance,
        p.Aroma,
        p.Taste,
        p.Aftertaste,
        p.Overall,
        p["AWS Score"],
        p["100pt Scale"]
    ]);
    dv.table(
        ["Tasting", "Date", "Taster", "Appear", "Aroma", "Taste", "Aftertaste", "Overall", "AWS", "100pt"],
        rows
    );
}
```

### Create New Tasting

```dataviewjs
const bottleName = dv.current().file.name;
const folderPath = `1_Wines/${bottleName}`;

// Create container
const container = dv.container;

// Create button
const button = dv.el('button', 'Add New Tasting');
button.style.padding = '8px 16px';
button.style.backgroundColor = '#4CAF50';
button.style.color = 'white';
button.style.border = 'none';
button.style.borderRadius = '4px';
button.style.cursor = 'pointer';
button.style.fontSize = '14px';
button.style.marginBottom = '10px';

// Create form (hidden by default)
const form = container.createEl('div');
form.style.display = 'none';
form.style.padding = '15px';
form.style.border = '1px solid #ccc';
form.style.borderRadius = '4px';
form.style.marginTop = '10px';
form.style.backgroundColor = 'var(--background-primary)';

form.innerHTML = `
    <h3>New Wine Tasting</h3>
    <div style="margin-bottom: 10px;">
        <label style="display: block; margin-bottom: 5px;">Date (YYYY-MM-DD):</label>
        <input type="text" id="tasting-date" value="${new Date().toISOString().split('T')[0]}" style="width: 100%; padding: 5px;">
    </div>
    <div style="margin-bottom: 10px;">
        <label style="display: block; margin-bottom: 5px;">Taster Name:</label>
        <input type="text" id="tasting-taster" style="width: 100%; padding: 5px;">
    </div>
    <button id="create-tasting-btn" style="padding: 8px 16px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px;">Create</button>
    <button id="cancel-tasting-btn" style="padding: 8px 16px; background-color: #ccc; color: black; border: none; border-radius: 4px; cursor: pointer;">Cancel</button>
`;

// Toggle form visibility
button.addEventListener('click', () => {
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
});

// Cancel button
form.querySelector('#cancel-tasting-btn').addEventListener('click', () => {
    form.style.display = 'none';
});

// Create button
form.querySelector('#create-tasting-btn').addEventListener('click', async () => {
    try {
        const date = form.querySelector('#tasting-date').value;
        const taster = form.querySelector('#tasting-taster').value;

        if (!date || !taster) {
            new Notice("Date and Taster Name are required!");
            return;
        }

        // Read template
        const templatePath = "9_Templates/Wine Tasting.md";
        const template = await app.vault.adapter.read(templatePath);

        // Replace template variables
        let content = template
            .replace(/{{value:Date}}/g, date)
            .replace(/{{value:TasterName}}/g, taster)
            .replace(/{{value:LinkedBottle}}/g, `[[${bottleName}]]`);

        // Create file
        const fileName = `Tasting-${date}-${taster}.md`;
        const filePath = `${folderPath}/${fileName}`;

        await app.vault.create(filePath, content);

        // Open the new file
        const file = app.vault.getAbstractFileByPath(filePath);
        await app.workspace.getLeaf().openFile(file);

        new Notice("Wine tasting created successfully!");

        // Hide and reset form
        form.style.display = 'none';
        form.querySelector('#tasting-date').value = new Date().toISOString().split('T')[0];
        form.querySelector('#tasting-taster').value = '';
    } catch (error) {
        console.error("Error creating tasting:", error);
        new Notice(`Error: ${error.message}`);
    }
});
```

## Label
Label:: ![[1_Wines/Caymus Vineyards - 1858 Cabernet Sauvignon - 2021/labels/label.jpg]]
