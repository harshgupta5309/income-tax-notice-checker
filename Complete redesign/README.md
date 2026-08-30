# ⚖️ Income Tax Notice Checker

A modern Windows desktop application that automates the process of checking for new Income Tax notices on the Indian e-Filing portal. Built with **Playwright** for browser automation and **CustomTkinter** for a sleek, dark-mode GUI.

## Features

- **Automated Login & Download**: Logs into the Income Tax e-Filing portal for each client listed in your credentials file, navigates to e-Proceedings, and downloads CSV snapshots.
- **Smart Comparison**: Compares new downloads against previous snapshots to flag **new notices** and **updated fields**.
- **Formatted Excel Report**: Generates a professional `New_Notices_Flagged_Report.xlsx` with color-coded headers and frozen panes.
- **Archive Management**: Automatically archives older CSV snapshots to keep your working directory clean.
- **Modern GUI**: Dark-mode interface with live log streaming — no terminal needed.
- **Portable**: Fully portable `.exe` — no Python installation required on the target machine.

## Getting Started

### Prerequisites (for running from source)

```bash
pip install pandas openpyxl xlsxwriter playwright playwright-stealth customtkinter
playwright install chromium
```

### Running from Source

```bash
python income_tax_gui.py
```

### Running the .exe

1. Place `IncomeTaxNoticeChecker.exe` in any folder.
2. Place your `Credentials.xlsx` in the **same folder** (or use the Browse button to pick it).
3. Launch the `.exe`.
4. Click **Start Notice Check**.

### Credentials File Format

Your `Credentials.xlsx` must have exactly these column headers:

| Login_ID | Password | Name |
|----------|----------|------|
| PAN1234A | pass123  | John |
| PAN5678B | pass456  | Jane |

## Building the .exe

```bash
pyinstaller --noconfirm --onefile --windowed ^
  --name "IncomeTaxNoticeChecker" ^
  --hidden-import=playwright ^
  --hidden-import=playwright.sync_api ^
  --hidden-import=playwright_stealth ^
  --hidden-import=openpyxl ^
  --hidden-import=xlsxwriter ^
  income_tax_gui.py
```

> **Note**: Playwright's Chromium browser (~150 MB) is NOT bundled inside the `.exe`. You must run `playwright install chromium` once on the target machine, or set `PLAYWRIGHT_BROWSERS_PATH` to a portable location.

## Output

- **`New_Notices_Flagged_Report.xlsx`** — The main report with all flagged notices.
- **`Archive/`** — Older CSV snapshots are moved here automatically.

## License

MIT
