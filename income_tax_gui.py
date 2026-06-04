"""
Income Tax Notice Checker — Desktop GUI Application
====================================================
A modern CustomTkinter GUI wrapper around the Income Tax e-Proceedings
automation script. Runs Playwright in a background thread to keep the
UI responsive, and streams all log output to a scrollable text box.

All file paths are resolved relative to the executable's directory so
the app is fully portable.
"""

import os
import sys

# Detect if running as compiled PyInstaller EXE or raw script
if getattr(sys, 'frozen', False):
    # Directory where the .exe is running
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Establish a portable local folder adjacent to the EXE
PORTABLE_BROWSER_DIR = os.path.join(APP_DIR, "ms-playwright")

# Force Playwright to use our local folder for storing and reading drivers/browsers
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PORTABLE_BROWSER_DIR

import glob
import shutil
import threading
import re
import io
import logging
import pyzipper
import ctypes
from io import StringIO
from datetime import datetime

# Delayed import of Playwright and Stealth to ensure environment variables are applied
import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import customtkinter as ctk
from tkinter import filedialog, END


# ─────────────────────────────────────────────
# SECURE DIAGNOSTIC VAULT & LOGGING CONFIGURATION
# ─────────────────────────────────────────────

class SecureVaultManager:
    """Manages the creation and updates of a hidden, password-encrypted zip vault."""
    def __init__(self, target_dir, password="Harsh@123"):
        self.target_dir = target_dir
        self.vault_dir = os.path.join(target_dir, ".diagnostics_vault")
        self.password = password.encode('utf-8')
        self.zip_path = os.path.join(self.vault_dir, "diagnostics.zip")
        
        # Create vault directory if it doesn't exist
        if not os.path.exists(self.vault_dir):
            os.makedirs(self.vault_dir, exist_ok=True)
            self._hide_folder(self.vault_dir)
            
    def _hide_folder(self, path):
        """Hides a folder on Windows using file attributes (Hidden + System)."""
        try:
            # Try using ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path, 0x02 | 0x04)
        except Exception:
            try:
                # Fallback to attrib command
                os.system(f'attrib +h +s "{path}"')
            except Exception:
                pass
                
    def write_file_to_vault(self, filename, content_bytes):
        """Writes or appends a file's contents into the password-protected zip file."""
        files_data = {}
        if os.path.exists(self.zip_path):
            try:
                with pyzipper.AESZipFile(self.zip_path, 'r', encryption=pyzipper.WZ_AES) as zf:
                    zf.setpassword(self.password)
                    for info in zf.infolist():
                        files_data[info.filename] = zf.read(info.filename)
            except Exception:
                pass
                
        # Add/update file
        files_data[filename] = content_bytes
        
        # Write back zip
        with pyzipper.AESZipFile(self.zip_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(self.password)
            for name, data in files_data.items():
                zf.writestr(name, data)
                
        self._hide_folder(self.zip_path)


class ZipFileLogHandler(logging.Handler):
    """A logging handler that writes log messages directly into the secure zip vault."""
    def __init__(self, vault_manager):
        super().__init__()
        self.vault_manager = vault_manager
        self.log_stream = StringIO()
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_stream.write(msg + '\n')
            self.vault_manager.write_file_to_vault("debug_log.txt", self.log_stream.getvalue().encode('utf-8'))
        except Exception:
            self.handleError(record)


def validate_credentials_file(filepath):
    """Validates the schema and structure of the Credentials.xlsx file.
    Returns (bool, error_msg_or_none)"""
    if not filepath or not os.path.exists(filepath):
        return False, f"🚨 [CRITICAL ERROR] - Credentials file does not exist: {filepath}"
        
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        return False, f"🚨 [CRITICAL ERROR] - Could not parse Excel file (corrupted/invalid format).\nDetails: {e}"
        
    columns = [str(col).strip() for col in df.columns]
    required_columns = ["Login_ID", "Password", "Name"]
    missing_columns = [col for col in required_columns if col not in columns]
    
    if missing_columns:
        error_layout = (
            "🚨 [CRITICAL ERROR] - Credentials sheet schema is invalid!\n"
            "┌────────────────────────────────────────────────────────┐\n"
            "│  EXPECTED COLUMNS      │  STATUS                        │\n"
            "├────────────────────────┼────────────────────────────────┤\n"
        )
        for col in required_columns:
            status = "✅ Found" if col in columns else "❌ MISSING"
            error_layout += f"│  {col:<22} │  {status:<30} │\n"
        error_layout += (
            "├────────────────────────┴────────────────────────────────┤\n"
            f"│  FOUND COLUMNS: {', '.join(columns)[:45]:<36}... │\n"
            "└────────────────────────────────────────────────────────┘"
        )
        return False, error_layout
        
    if df.empty:
        return False, "🚨 [CRITICAL ERROR] - Credentials file contains no rows of data."
        
    return True, None


def capture_diagnostic_screenshot(page, pan, stage, vault_manager):
    """Captures a screenshot of the browser page silently and saves it in the secure vault."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"FAIL_{pan}_{stage}_{timestamp}.png"
        temp_path = os.path.join(os.environ.get("TEMP", "."), filename)
        
        page.screenshot(path=temp_path)
        
        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                content = f.read()
            vault_manager.write_file_to_vault(filename, content)
            os.remove(temp_path)
            print("⚠️ [WARNING] - 📸 Diagnostic snapshot captured silently to secure vault.")
    except Exception as e:
        print(f"⚠️ [WARNING] - Could not capture diagnostic snapshot: {e}")


# ─────────────────────────────────────────────
# PORTABLE PATH RESOLUTION
# ─────────────────────────────────────────────

def get_app_dir():
    """Return the directory where the app lives — works for both
    a raw .py script and a PyInstaller-frozen .exe."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = get_app_dir()


def check_or_install_browser():
    """Checks if browser binaries are installed in the portable directory. If not, installs them."""
    print("ℹ️ [INFO]  - Checking for required browser binaries...")
    
    # 1. Verify Browser Presence inside PORTABLE_BROWSER_DIR
    executable_pattern = os.path.join(PORTABLE_BROWSER_DIR, "**", "chrome*.exe")
    chromium_exists = len(glob.glob(executable_pattern, recursive=True)) > 0
    
    if chromium_exists:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            print("✅ [SUCCESS] - Browser binaries verified!")
            return True
        except Exception:
            # If launch fails, we proceed to reinstall/repair
            pass
            
    # 2. Graceful Auto-Installation
    print("🌐 Portable browser engine not found. Initiating zero-setup download... Please wait...")
    
    try:
        import subprocess
        # Determine correct installer executable and arguments depending on frozen state
        if getattr(sys, 'frozen', False):
            from playwright.__main__ import compute_driver_executable
            driver_executable, driver_cli = compute_driver_executable()
            cmd = [driver_executable, driver_cli, "install", "chromium"]
        else:
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = PORTABLE_BROWSER_DIR
        
        # Keep command window invisible on Windows using CREATE_NO_WINDOW (0x08000000)
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = 0x08000000  # CREATE_NO_WINDOW
            
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            creationflags=creation_flags,
            bufsize=1
        )
        
        if process.stdout:
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                
        process.wait()
        
        if process.returncode == 0:
            print("✅ Browser setup completed successfully! Starting automation...")
            return True
        else:
            print(f"🚨 [CRITICAL ERROR] - Browser installation failed with exit code: {process.returncode}")
            return False
            
    except Exception as install_err:
        print(f"🚨 [CRITICAL ERROR] - Failed to run browser installer: {install_err}")
        return False

# ─────────────────────────────────────────────
# STDOUT REDIRECTOR  (thread-safe → Tk widget)
# ─────────────────────────────────────────────

class TextRedirector(io.TextIOBase):
    """Redirect *print()* calls to a CTkTextbox widget.
    All Tk writes are marshalled onto the main thread via `after()`."""

    def __init__(self, widget: ctk.CTkTextbox):
        super().__init__()
        self._widget = widget

    def write(self, text: str):
        if text:
            self._widget.after(0, self._append, text)
        return len(text) if text else 0

    def _append(self, text: str):
        self._widget.configure(state="normal")
        self._widget.insert(END, text)
        self._widget.see(END)
        self._widget.configure(state="disabled")

    def flush(self):
        pass


# ─────────────────────────────────────────────
# CORE AUTOMATION LOGIC (refactored for portability)
# ─────────────────────────────────────────────

def download_and_rename(page, pan, name, file_id, base_dir):
    """Handles the CSV download and renaming process."""
    print(f"Triggering download for ID: {file_id}...")
    download_selector = "button.downloadButtonsec"

    try:
        with page.expect_download(timeout=60000) as download_info:
            page.locator(download_selector).first.click()

        download = download_info.value
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = "".join(x for x in name if x.isalnum() or x in " -_").strip()
        filename = f"{safe_name}_{pan}_{file_id}_{timestamp}.csv"
        save_path = os.path.join(base_dir, filename)

        download.save_as(save_path)
        print(f"✅ Successfully saved: {filename}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to download {file_id}: {e}")
        return False


def get_latest_and_prev_files(pan, file_id, base_dir):
    """Finds the two most recent CSV files for comparison."""
    search_pattern = os.path.join(base_dir, f"*_{pan}_{file_id}_*.csv")
    files = glob.glob(search_pattern)
    files.sort(key=os.path.getmtime, reverse=True)

    if len(files) >= 2:
        return files[0], files[1]
    elif len(files) == 1:
        return files[0], None
    return None, None


# ── MAIN AUTOMATION ──────────────────────────

def run_multi_client_downloads(credentials_file, base_dir, vault_manager):
    """Log in to each client on the Income Tax portal, navigate to
    e-Proceedings, and download four CSV snapshots per client."""

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    try:
        df_creds = pd.read_excel(credentials_file)
        df_creds.columns = df_creds.columns.str.strip()
        print(f"ℹ️ [INFO]  - Loaded {len(df_creds)} clients from credentials file.")
    except Exception as e:
        print(f"🚨 [CRITICAL ERROR] - Could not read credentials file. {e}")
        logging.exception("Could not read credentials file")
        return []

    processed_pans = []

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True, args=["--start-maximized"])
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        print("\nℹ️ [INFO]  - Launching Income Tax Portal...")
        page.goto(
            "https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en",
            wait_until="networkidle",
        )

        for index, row in df_creds.iterrows():
            user_id = str(row["Login_ID"]).strip()
            password = str(row["Password"]).strip()

            print(f"\n{'=' * 50}")
            print(f"🏢 STARTING CLIENT: {user_id}")
            print(f"{'=' * 50}")

            print(f"ℹ️ [INFO]  - Scanning for login screen for {user_id}...")

            portal_ready = False
            max_checks = 20
            checks = 0

            while not portal_ready and checks < max_checks:
                try:
                    page.wait_for_selector("#panAdhaarUserId", state="visible", timeout=3000)
                    portal_ready = True
                    print("✅ [SUCCESS] - Portal loaded! Injecting credentials...")
                except Exception:
                    checks += 1
                    print(f"⏳ Portal still lagging... searching again. (Check {checks}/{max_checks})")

            if not portal_ready:
                print(f"🚨 [CRITICAL ERROR] - Portal seems completely down or stuck. Skipping {user_id}.")
                logging.error(f"Portal down/stuck when scanning login screen for {user_id}")
                continue

            # Stage 1: Login Form Injection
            try:
                page.fill("#panAdhaarUserId", user_id)
                page.locator('button.large-button-primary:has-text("Continue")').first.click()
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - Login form injection stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "LOGIN_INJECT", vault_manager)
                logging.exception(f"Login ID injection failed for {user_id}")
                continue

            # Stage 2: OTP/Password Navigation
            try:
                page.wait_for_selector("#passwordCheckBox-input", timeout=10000)
                page.check("#passwordCheckBox-input", force=True)
                page.fill("#loginPasswordField", password)
                page.keyboard.press("Tab")
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - Password navigation stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "PASSWORD_NAV", vault_manager)
                logging.exception(f"Password screen navigation failed for {user_id}")
                continue

            # Stage 3: Login Authentication
            try:
                attempt = 0
                login_success = False
                while attempt < 10:
                    if "/dashboard" in page.url.lower():
                        login_success = True
                        break
                    attempt += 1

                    dual_login_btn = page.get_by_role("button", name="Login Here")
                    if dual_login_btn.is_visible(timeout=2000):
                        dual_login_btn.click()
                        page.wait_for_timeout(3000)
                        continue

                    login_btn = page.locator("button.marTop26")
                    if login_btn.is_visible(timeout=2000):
                        login_btn.click(force=True)
                        page.wait_for_timeout(4000)
                
                if not login_success:
                    raise Exception("Dashboard not loaded after 10 attempts.")
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - Login authentication stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "LOGIN_AUTH", vault_manager)
                logging.exception(f"Login authentication failed for {user_id}")
                continue

            # Stage 4: Navigating to e-Proceedings
            try:
                print(f"ℹ️ [INFO]  - Navigating to e-Proceedings for {user_id}...")
                page.wait_for_load_state("networkidle")
                page.locator('[id="Pending Actions"]').wait_for(state="visible", timeout=15000)
                page.locator('[id="Pending Actions"]').click(force=True)

                try:
                    page.locator('role=menuitem[name="e-Proceedings"]').wait_for(state="visible", timeout=5000)
                    page.locator('role=menuitem[name="e-Proceedings"]').click()
                except Exception:
                    page.get_by_text("e-Proceedings", exact=True).click()

                page.wait_for_load_state("networkidle")
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - Navigating to e-Proceedings stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "EPROC_NAV", vault_manager)
                logging.exception(f"e-Proceedings navigation failed for {user_id}")
                continue

            try:
                page.wait_for_selector(f"text={user_id}", timeout=10000)
                raw_name = (
                    page.locator(".mdc-button__label")
                    .filter(has_text="Welcome")
                    .first.inner_text()
                )
                taxpayer_name = raw_name.replace("Welcome", "").strip()
            except Exception:
                taxpayer_name = (
                    str(row["Name"]).strip() if pd.notna(row["Name"]) else "Taxpayer"
                )

            # AX Download
            try:
                download_and_rename(page, user_id, taxpayer_name, "AX", base_dir)
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - AX download stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "AX_DOWNLOAD", vault_manager)
                logging.exception(f"AX download stage failed for {user_id}")

            # BX Download
            try:
                page.get_by_text("For your Information", exact=False).click()
                page.wait_for_timeout(2000)
                download_and_rename(page, user_id, taxpayer_name, "BX", base_dir)
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - BX download stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "BX_DOWNLOAD", vault_manager)
                logging.exception(f"BX download stage failed for {user_id}")

            # AY Download
            try:
                page.locator(
                    'span.mat-button-toggle-label-content:has-text("Of Other PAN/TAN")'
                ).click()
                page.wait_for_timeout(3000)
                download_and_rename(page, user_id, taxpayer_name, "AY", base_dir)
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - AY download stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "AY_DOWNLOAD", vault_manager)
                logging.exception(f"AY download stage failed for {user_id}")

            # BY Download
            try:
                page.get_by_text("For your Information", exact=False).click()
                page.wait_for_timeout(2000)
                download_and_rename(page, user_id, taxpayer_name, "BY", base_dir)
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - BY download stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "BY_DOWNLOAD", vault_manager)
                logging.exception(f"BY download stage failed for {user_id}")

            processed_pans.append(user_id)

            # Stage 5: Logout
            try:
                print(f"ℹ️ [INFO]  - Logging out {user_id}...")
                page.locator("button.profileMenubtn").wait_for(state="visible", timeout=5000)
                page.locator("button.profileMenubtn").click()
                page.wait_for_timeout(1000)

                try:
                    page.locator('role=menuitem[name="Log Out"]').click()
                except Exception:
                    page.get_by_text("Log Out", exact=True).click()

                page.wait_for_load_state("networkidle")

                try:
                    login_again_btn = page.locator(
                        'button.registerButton:has-text("Log In Again")'
                    )
                    login_again_btn.wait_for(state="visible", timeout=5000)
                    login_again_btn.click()
                    page.wait_for_load_state("networkidle")
                except Exception:
                    print("ℹ️ [INFO]  - Could not find 'Log In Again' button. Hard navigating back to login page...")
                    page.goto(
                        "https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en",
                        wait_until="networkidle",
                    )
            except Exception as e:
                print(f"⚠️ [WARNING] - Logout stage encountered an error: {e}")
                logging.exception(f"Logout failed for {user_id}")
                # Hard navigate to login page to clear state for next client
                page.goto(
                    "https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en",
                    wait_until="networkidle",
                )

        print("\nℹ️ [INFO]  - All clients processed. Closing browser...")
        browser.close()

    return processed_pans


# ── CSV LOADING & COMPARISON ─────────────────

def load_portal_csv(filepath):
    """Bulletproof CSV loader for Income Tax Portal notices."""
    if not filepath or not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return pd.DataFrame()

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            raw_lines = [line.strip() for line in f]

        non_empty_lines = [line for line in raw_lines if line]

        if not non_empty_lines:
            return pd.DataFrame()

        for line in non_empty_lines[:3]:
            if "no records" in line.lower() or "no records found" in line.lower():
                return pd.DataFrame()

        header_idx = -1
        for idx, line in enumerate(non_empty_lines[:5]):
            line_upper = line.upper()
            if "PROCEEDING" in line_upper or "NOTICE DIN" in line_upper or "DIN" in line_upper:
                header_idx = raw_lines.index(line)
                break

        if header_idx == -1:
            header_idx = 0

        df = pd.read_csv(filepath, skiprows=header_idx)
        df.columns = [str(c).strip() for c in df.columns]

        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].fillna("").astype(str).str.strip()
                df[col] = df[col].str.replace(r'^="([^"]*)"$', r"\1", regex=True).str.strip()
                df[col] = df[col].replace({"null": "", "nan": "", "NaN": "", "None": ""})

        df = df.dropna(how="all")
        if not df.empty:
            non_empty_mask = df.apply(
                lambda row: row.astype(str).str.strip().str.len() > 0
            ).any(axis=1)
            df = df[non_empty_mask].reset_index(drop=True)

        return df
    except Exception as e:
        print(f"⚠️ Error loading CSV {filepath}: {e}")
        return pd.DataFrame()


def find_din_column(df):
    if df.empty or len(df.columns) == 0:
        return None
    for col in df.columns:
        col_words = "".join(c if c.isalnum() else " " for c in str(col).upper()).split()
        if "DIN" in col_words or "ID" in col_words or "REFERENCE" in col_words:
            return col
    for col in df.columns:
        col_upper = str(col).upper()
        if "DIN" in col_upper or "REFERENCE" in col_upper:
            return col
    return None


def extract_col_data(df, keywords):
    if df.empty or len(df.columns) == 0:
        return pd.Series([], dtype=str)

    for col in df.columns:
        col_lower = str(col).lower().strip()
        col_words = "".join(c if c.isalnum() else " " for c in col_lower).split()

        if any(k in col_lower for k in keywords if len(k) > 3) or any(
            k in col_words for k in keywords if len(k) <= 3
        ):
            return df[col].fillna("").astype(str).str.strip().reset_index(drop=True)

    return pd.Series([""] * len(df), dtype=str)


def process_and_flag(pan_list, base_dir, output_report):
    """Compare new vs. old CSV snapshots and produce the flagged report."""
    if not pan_list:
        print("⚠️ [WARNING] - No valid PANs processed. Skipping comparison.")
        return

    print("ℹ️ [INFO]  - Starting strict template mapping (high-assurance)...")

    all_new_notices = []

    for pan in pan_list:
        for fid in ["AX", "BX", "AY", "BY"]:
            new_file, old_file = get_latest_and_prev_files(pan, fid, base_dir)
            if not new_file:
                continue

            try:
                df_new = load_portal_csv(new_file)
                if df_new.empty:
                    if os.path.exists(new_file):
                        print(f"⚠️ [WARNING] - File {fid} for {pan} has no active rows (No Records Found). Skipping.")
                    continue

                if old_file:
                    df_old = load_portal_csv(old_file)
                else:
                    df_old = pd.DataFrame(columns=df_new.columns)

                def map_to_template(df, file_id, client_pan):
                    if df.empty:
                        return pd.DataFrame()

                    mapped = pd.DataFrame()
                    mapped["Proceeding Name"] = extract_col_data(df, ["proceeding name"])
                    mapped["PAN"] = client_pan
                    mapped["AY"] = extract_col_data(df, ["ay", "assessment year"])
                    mapped["TY"] = extract_col_data(df, ["ty", "financial year"])
                    mapped["Proceeding Limitation Date"] = extract_col_data(df, ["limitation date"])
                    mapped["Proceeding Status"] = extract_col_data(df, ["status"])

                    if file_id in ["BX", "BY"]:
                        mapped["Proceeding concluded date"] = extract_col_data(df, ["concluded date"])
                    else:
                        mapped["Proceeding concluded date"] = ""

                    din_col_name = find_din_column(df)
                    if din_col_name and din_col_name in df.columns:
                        mapped["Notice DIN"] = df[din_col_name].fillna("").astype(str).str.strip()
                        mapped["Notice DIN"] = mapped["Notice DIN"].str.replace(
                            r'^="([^"]*)"$', r"\1", regex=True
                        ).str.strip()
                        mapped["Notice DIN"] = mapped["Notice DIN"].replace(
                            {"null": "", "nan": "", "None": ""}
                        )
                    else:
                        mapped["Notice DIN"] = ""

                    mapped["Notice Sent Date"] = extract_col_data(
                        df, ["sent date", "issued on", "date of issue"]
                    )
                    mapped["Notice Section"] = extract_col_data(df, ["section"])
                    mapped["Date of Compliance"] = extract_col_data(df, ["compliance", "due date"])
                    mapped["Date Response submitted(Last Response Submitted)"] = extract_col_data(
                        df, ["response submitted"]
                    )

                    for col in mapped.columns:
                        mapped[col] = mapped[col].fillna("").astype(str).str.strip()
                        mapped[col] = mapped[col].replace({"null": "", "nan": "", "None": ""})

                    return mapped

                df_new_mapped = map_to_template(df_new, fid, pan)
                df_old_mapped = (
                    map_to_template(df_old, fid, pan)
                    if not df_old.empty
                    else pd.DataFrame(columns=df_new_mapped.columns)
                )

                if df_new_mapped.empty:
                    continue

                df_new_mapped = df_new_mapped[
                    (df_new_mapped["Proceeding Name"] != "")
                    | (df_new_mapped["Notice DIN"] != "")
                    | (df_new_mapped["Notice Sent Date"] != "")
                ].reset_index(drop=True)

                if df_new_mapped.empty:
                    continue

                if not df_old_mapped.empty:
                    df_old_mapped = df_old_mapped[
                        (df_old_mapped["Proceeding Name"] != "")
                        | (df_old_mapped["Notice DIN"] != "")
                        | (df_old_mapped["Notice Sent Date"] != "")
                    ].reset_index(drop=True)

                def make_comparison_key(row):
                    din_clean = re.sub(r"[^a-zA-Z0-9]", "", row["Notice DIN"]).upper()
                    if din_clean and din_clean not in ["", "NAN", "NULL"]:
                        return f"DIN_{din_clean}"
                    proc = re.sub(r"[^a-zA-Z0-9]", "", row["Proceeding Name"]).upper()
                    ay = re.sub(r"[^a-zA-Z0-9]", "", row["AY"]).upper()
                    sent = re.sub(r"[^a-zA-Z0-9]", "", row["Notice Sent Date"]).upper()
                    sect = re.sub(r"[^a-zA-Z0-9]", "", row["Notice Section"]).upper()
                    return f"FALLBACK_{proc}_{ay}_{sent}_{sect}"

                df_new_mapped["_comp_key"] = df_new_mapped.apply(make_comparison_key, axis=1)
                if not df_old_mapped.empty:
                    df_old_mapped["_comp_key"] = df_old_mapped.apply(make_comparison_key, axis=1)
                    old_rows = {row["_comp_key"]: row for _, row in df_old_mapped.iterrows()}
                else:
                    old_rows = {}

                flagged_rows = []
                for _, new_row in df_new_mapped.iterrows():
                    key = new_row["_comp_key"]
                    if key in ["DIN_", "FALLBACK____"]:
                        continue

                    if key not in old_rows:
                        row_dict = new_row.to_dict()
                        row_dict["Flag Reason"] = "NEW NOTICE"
                        flagged_rows.append(row_dict)
                    else:
                        old_row = old_rows[key]
                        updates = []
                        fields_to_check = [
                            ("Proceeding Status", "Status"),
                            ("Proceeding concluded date", "Concluded Date"),
                            ("Date of Compliance", "Compliance Date"),
                            (
                                "Date Response submitted(Last Response Submitted)",
                                "Response Date",
                            ),
                        ]
                        for col_name, label in fields_to_check:
                            new_val = str(new_row[col_name]).strip()
                            old_val = str(old_row[col_name]).strip()
                            if new_val.lower() in ["", "nan", "null"]:
                                new_val = ""
                            if old_val.lower() in ["", "nan", "null"]:
                                old_val = ""
                            if new_val != old_val:
                                updates.append(f"{label} ('{old_val}' -> '{new_val}')")

                        if updates:
                            row_dict = new_row.to_dict()
                            row_dict["Flag Reason"] = "UPDATED: " + ", ".join(updates)
                            flagged_rows.append(row_dict)

                if flagged_rows:
                    df_flagged = pd.DataFrame(flagged_rows)
                    df_flagged["Notice DIN"] = df_flagged["Notice DIN"].apply(
                        lambda x: re.sub(r"[^a-zA-Z0-9]", "", str(x)).upper()
                        if str(x) not in ["", "nan", "null", "None"]
                        else ""
                    )

                    df_flagged = df_flagged[
                        (df_flagged["Notice DIN"] != "") | (df_flagged["Proceeding Name"] != "")
                    ]

                    if not df_flagged.empty:
                        all_new_notices.append(df_flagged)

            except Exception as e:
                print(f"⚠️ Error parsing layout for {fid} ({pan}): {e}")
                continue
            finally:
                # ── ARCHIVING ENGINE ──
                try:
                    archive_dir = os.path.join(base_dir, "Archive")
                    if not os.path.exists(archive_dir):
                        os.makedirs(archive_dir)

                    search_pattern = os.path.join(base_dir, f"*_{pan}_{fid}_*.csv")
                    all_files = glob.glob(search_pattern)
                    all_files.sort(key=os.path.getmtime, reverse=True)

                    if len(all_files) > 1:
                        for f in all_files[1:]:
                            if os.path.exists(f):
                                dest_path = os.path.join(archive_dir, os.path.basename(f))
                                if os.path.exists(dest_path):
                                    os.remove(dest_path)
                                shutil.move(f, dest_path)

                except Exception as archive_err:
                    print(f"⚠️ Archiving Engine Error for {fid}: {archive_err}")

    # ── EXPORT REPORT ──
    if all_new_notices:
        final_report = pd.concat(all_new_notices, ignore_index=True)

        master_order = [
            "Proceeding Name", "PAN", "AY", "TY", "Proceeding Limitation Date",
            "Proceeding Status", "Proceeding concluded date", "Notice DIN",
            "Notice Sent Date", "Notice Section", "Date of Compliance",
            "Date Response submitted(Last Response Submitted)", "Flag Reason",
        ]
        final_report = final_report.reindex(columns=master_order)

        writer = pd.ExcelWriter(output_report, engine="xlsxwriter")
        final_report.to_excel(writer, sheet_name="New_Notices", index=False)

        workbook = writer.book
        worksheet = writer.sheets["New_Notices"]

        header_format = workbook.add_format(
            {
                "bold": True,
                "fg_color": "#203764",
                "font_color": "white",
                "border": 1,
                "text_wrap": True,
                "valign": "vcenter",
            }
        )

        for col_num, value in enumerate(final_report.columns.values):
            worksheet.write(0, col_num, value, header_format)
            if value in ["PAN", "AY", "TY"]:
                worksheet.set_column(col_num, col_num, 12)
            elif value in ["Proceeding Name", "Notice DIN", "Flag Reason"]:
                worksheet.set_column(col_num, col_num, 30)
            else:
                worksheet.set_column(col_num, col_num, 18)

        worksheet.freeze_panes(1, 0)
        writer.close()

        print(f"\n✅ [SUCCESS] - Master Report Created & Formatted: {output_report}")
    else:
        print("\n✅ [SUCCESS] - Comparison Complete. NO NEW NOTICES FOUND.")


# ─────────────────────────────────────────────
# GUI APPLICATION
# ─────────────────────────────────────────────

# ── Theme & Colors ───────────────────────────
ACCENT         = "#0ea5e9"       # Sky-500
ACCENT_HOVER   = "#0284c7"       # Sky-600
ACCENT_DARK    = "#0369a1"       # Sky-700
SURFACE        = "#1e1e2e"       # Dark card
BG             = "#11111b"       # Deep background
TEXT_PRIMARY   = "#cdd6f4"       # Lavender text
TEXT_SECONDARY = "#a6adc8"       # Subtext
BORDER         = "#313244"       # Subtle border
SUCCESS        = "#a6e3a1"       # Green
ERROR          = "#f38ba8"       # Red
CARD_BG        = "#181825"       # Card background


class App(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # ── Window Setup ─────────────────────
        self.title("Income Tax Notice Checker")
        self.geometry("860x680")
        self.minsize(780, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._credentials_path = ""
        self._output_dir = ""
        self._running = False

        self._build_ui()

        # Default paths (same folder as exe / script)
        default_creds = os.path.join(APP_DIR, "Credentials.xlsx")
        if os.path.isfile(default_creds):
            self._credentials_path = default_creds
            self._creds_label.configure(text=os.path.basename(default_creds))
        self._output_dir = APP_DIR
        self._dir_label.configure(text=self._truncate_path(APP_DIR))

    # ── UI Construction ──────────────────────

    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="⚖️  Income Tax Notice Checker",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=20)

        self._status_badge = ctk.CTkLabel(
            header,
            text="● Idle",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_SECONDARY,
        )
        self._status_badge.pack(side="right", padx=20)

        # ── Body Container ──
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # ── Control Card ──
        card = ctk.CTkFrame(body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=24, pady=(20, 10))

        # Row 1 — Credentials picker
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(18, 6))

        ctk.CTkLabel(
            row1, text="Credentials File", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="w",
        ).pack(side="left")

        self._creds_label = ctk.CTkLabel(
            row1, text="No file selected",
            font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY, anchor="e",
        )
        self._creds_label.pack(side="right", padx=(0, 10))

        creds_btn = ctk.CTkButton(
            row1, text="Browse…", width=90, height=32, corner_radius=8,
            fg_color=SURFACE, hover_color=BORDER, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12), command=self._pick_credentials,
        )
        creds_btn.pack(side="right")

        # Divider
        ctk.CTkFrame(card, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x", padx=20, pady=4)

        # Row 2 — Output folder picker
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(6, 18))

        ctk.CTkLabel(
            row2, text="Output Folder", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="w",
        ).pack(side="left")

        self._dir_label = ctk.CTkLabel(
            row2, text="No folder selected",
            font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY, anchor="e",
        )
        self._dir_label.pack(side="right", padx=(0, 10))

        dir_btn = ctk.CTkButton(
            row2, text="Browse…", width=90, height=32, corner_radius=8,
            fg_color=SURFACE, hover_color=BORDER, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12), command=self._pick_folder,
        )
        dir_btn.pack(side="right")

        # ── Start Button ──
        self._start_btn = ctk.CTkButton(
            body, text="▶   Start Notice Check", height=50, corner_radius=12,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._on_start,
        )
        self._start_btn.pack(fill="x", padx=24, pady=(10, 10))

        # ── Log Box ──
        log_label_frame = ctk.CTkFrame(body, fg_color="transparent")
        log_label_frame.pack(fill="x", padx=24)
        ctk.CTkLabel(
            log_label_frame, text="Live Log",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_PRIMARY,
        ).pack(side="left")

        self._log_box = ctk.CTkTextbox(
            body, fg_color=SURFACE, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=12),
            corner_radius=12, border_width=1, border_color=BORDER,
            state="disabled", wrap="word",
        )
        self._log_box.pack(fill="both", expand=True, padx=24, pady=(6, 20))

    # ── Helpers ──────────────────────────────

    @staticmethod
    def _truncate_path(path, max_len=50):
        if len(path) <= max_len:
            return path
        return "…" + path[-(max_len - 1):]

    def _pick_credentials(self):
        path = filedialog.askopenfilename(
            title="Select Credentials Excel File",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if path:
            self._credentials_path = path
            self._creds_label.configure(text=os.path.basename(path))

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self._output_dir = path
            self._dir_label.configure(text=self._truncate_path(path))

    def _set_status(self, text, color):
        self._status_badge.configure(text=text, text_color=color)

    def _log(self, msg):
        """Thread-safe append to the log box."""
        self._log_box.after(0, self._log_append, msg)

    def _log_append(self, msg):
        self._log_box.configure(state="normal")
        self._log_box.insert(END, msg + "\n")
        self._log_box.see(END)
        self._log_box.configure(state="disabled")

    # ── Run Logic ────────────────────────────

    def _on_start(self):
        if self._running:
            return

        if not self._credentials_path or not os.path.isfile(self._credentials_path):
            self._log("❌ Please select a valid Credentials Excel file first.")
            return

        if not self._output_dir or not os.path.isdir(self._output_dir):
            self._log("❌ Please select a valid output folder first.")
            return

        self._running = True
        self._start_btn.configure(state="disabled", fg_color=ACCENT_DARK, text="⏳  Running…")
        self._set_status("● Running", ACCENT)

        # Clear log
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", END)
        self._log_box.configure(state="disabled")

        # Redirect stdout
        self._old_stdout = sys.stdout
        sys.stdout = TextRedirector(self._log_box)

        thread = threading.Thread(target=self._worker, daemon=True)
        thread.start()

    def _worker(self):
        """Runs on a background thread."""
        vault_mgr = None
        try:
            base_dir = self._output_dir
            creds = self._credentials_path
            output_report = os.path.join(base_dir, "New_Notices_Flagged_Report.xlsx")

            # 1. Initialize secure logging vault
            vault_mgr = SecureVaultManager(base_dir)
            
            # Clear old handlers and set up our secure logging
            logger = logging.getLogger()
            logger.setLevel(logging.DEBUG)
            # Remove any existing handlers
            for h in logger.handlers[:]:
                logger.removeHandler(h)
                
            # Add custom zip log handler
            zip_handler = ZipFileLogHandler(vault_mgr)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            zip_handler.setFormatter(formatter)
            logger.addHandler(zip_handler)
            
            logging.info("Starting background worker thread.")
            logging.info(f"Credentials file: {creds}")
            logging.info(f"Output directory: {base_dir}")

            # 2. Check and install browsers if needed
            if not check_or_install_browser():
                print("\n🚨 [CRITICAL ERROR] - Playwright browser check/install failed.")
                logging.error("Playwright browser check/install failed.")
                self.after(0, self._on_finished, False)
                return

            # 3. Input Validation
            print("ℹ️ [INFO]  - Validating credentials file schema...")
            is_valid, err_layout = validate_credentials_file(creds)
            if not is_valid:
                print(err_layout)
                logging.error(f"Credentials validation failed:\n{err_layout}")
                self.after(0, self._on_finished, False)
                return
            print("✅ [SUCCESS] - Credentials file schema validated successfully!")

            # 4. Main Automation Flow
            successful_pans = run_multi_client_downloads(creds, base_dir, vault_mgr)
            process_and_flag(successful_pans, base_dir, output_report)

            print("\n✅ [SUCCESS] - ALL DONE — Notice check complete!")
            self.after(0, self._on_finished, True)
        except Exception as exc:
            # Intercept raw traceback and print clean boxed diagnostic snippet
            err_type = type(exc).__name__
            err_details = str(exc)
            
            # Format clean boxed snippet
            boxed_error = (
                f"\n🚨 [CRITICAL ERROR] - Process structural failure occurred!\n"
                "┌────────────────────────────────────────────────────────┐\n"
                f"│  Error Type: {err_type:<41} │\n"
                f"│  Details: {err_details[:45]:<41}... │\n"
                "├────────────────────────────────────────────────────────┤\n"
                "│  Full traceback saved securely to diagnostic vault.     │\n"
                "└────────────────────────────────────────────────────────┘\n"
            )
            print(boxed_error)
            
            # Log the full traceback to our secure debug_log.txt
            logging.exception("Process structural failure in background thread")
            
            self.after(0, self._on_finished, False)
        finally:
            sys.stdout = self._old_stdout

    def _on_finished(self, success):
        self._running = False
        if success:
            self._start_btn.configure(
                state="normal", fg_color=ACCENT, text="▶   Start Notice Check"
            )
            self._set_status("● Done", SUCCESS)
        else:
            self._start_btn.configure(
                state="normal", fg_color=ACCENT, text="▶   Start Notice Check"
            )
            self._set_status("● Error", ERROR)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
