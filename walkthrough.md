# Litigation OS — Enhancements, Hotkeys & Help Documentation Walkthrough

We have successfully resolved the Playwright timeout error, integrated comprehensive keyboard shortcuts, implemented a server delay choice prompt, added a BETA badge and credit, and designed an interactive Help Manual modal.

---

## 🛠️ Resolved Issues & Enhancements

### 1. Robust Server Timeout Prompting 🚨
- **The Bug**: Playwright timed out (10s/20s) when the portal server was slow or fluctuating, causing execution crashes.
- **The Solution**:
  - Integrated default timeouts (`30s` context / `30s` navigation) and safety checks around initial portal navigation.
  - Implemented `prompt_user_server_delay(pan, selector)` inside Python background thread that signals the Javascript frontend via `showServerDelayPrompt` and blocks thread execution using a `threading.Event()`.
  - Added an elegant choice prompt box directly below the active client taxpayer name.
  - The user can select:
    - **Wait (30s)**: Signals backend to retry the element wait for another 30 seconds.
    - **Skip Client**: Raises a `SkipClientException` in Python to cleanly move to the next taxpayer.
    - **Stop Pipeline**: Raises a `StopPipelineException` to abort the automation run immediately.

### 2. Comprehensive Keyboard Shortcuts & UI Labels ⌨️
- **The Action**: Visual shortcuts have been added next to names in small letter badges, and global listeners capture hotkeys.
- **Shortcut Registry**:
  - `Ctrl + Enter`: Sync Notices (triggers the main scraper thread)
  - `Ctrl + O`: Choose Credentials spreadsheet
  - `Ctrl + N`: Choose Download Folder
  - `1`: Switch to **Operational Monitor** tab
  - `2`: Switch to **Litigation Suite** dossier view
  - `Ctrl + F`: Toggle **Full Screen** mode (utilizes native PyWebView `window.toggle_fullscreen()` with HTML5 fallback)
  - `F1` or `tab`: Open/Close **Help Manual** modal

### 3. Header BETA Badge & Credit 🏷️
- **The Action**: Added branding at the top-left title.
- **Layout**: Displays `BETA` styled as a rust-bordered tag next to "Litigation OS", with a small credit line saying "by Harsh Gupta" in `JetBrains Mono` font.

### 4. Interactive Help Modal 📖
- **The Action**: Added a Help tab button next to the Litigation Suite button.
- **Design**: Opens a gorgeous modal sheet detailed with HSL-tailored borders and obsidian backgrounds. Explains the step-by-step extraction workflow and houses the complete hotkey registry.

---

## 📦 Standalone Binary Compilation

- **Executable**: Compiled successfully into `dist/LitigationOS.exe`.
- **Footprint size**: Built at **94.65 MB**, which fully complies with the 103MB size limit constraint.
