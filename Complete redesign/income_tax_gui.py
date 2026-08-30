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

def download_and_rename(page, pan, name, file_id, base_dir, app_callback=None):
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
        
        # Calculate size and check for "No Records Found"
        file_size_bytes = os.path.getsize(save_path)
        is_no_records = False
        if file_size_bytes == 0:
            is_no_records = True
        else:
            try:
                with open(save_path, "r", encoding="utf-8", errors="ignore") as f:
                    first_lines = [f.readline().lower() for _ in range(3)]
                for line in first_lines:
                    if "no records" in line:
                        is_no_records = True
                        break
            except Exception:
                pass

        size_str = f"{file_size_bytes / 1024:.1f} KB"
        
        if is_no_records:
            status_text = "No Records Found"
            status_type = "warning"
        else:
            status_text = "Saved Successfully"
            status_type = "success"

        if app_callback:
            app_callback.add_ledger_entry(file_id, filename, status_text, size_str, status_type=status_type)

        return True
    except Exception as e:
        print(f"⚠️ Failed to download {file_id}: {e}")
        if app_callback:
            safe_name = "".join(x for x in name if x.isalnum() or x in " -_").strip()
            filename = f"{safe_name}_{pan}_{file_id}_FAIL.csv"
            app_callback.add_ledger_entry(file_id, filename, "Download Failed", "0.0 KB", status_type="danger")
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

def run_multi_client_downloads(credentials_file, base_dir, vault_manager, app_callback=None):
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
            client_name = str(row["Name"]).strip() if pd.notna(row["Name"]) else "Taxpayer"

            print(f"\n{'=' * 50}")
            print(f"🏢 STARTING CLIENT: {user_id}")
            print(f"{'=' * 50}")

            print(f"ℹ️ [INFO]  - Scanning for login screen for {user_id}...")

            if app_callback:
                app_callback.start_client_timer(client_name, user_id)

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
                if app_callback:
                    app_callback.trigger_fast_forward()
                continue

            # Stage 1: Login Form Injection
            try:
                page.fill("#panAdhaarUserId", user_id)
                page.locator('button.large-button-primary:has-text("Continue")').first.click()
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - Login form injection stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "LOGIN_INJECT", vault_manager)
                logging.exception(f"Login ID injection failed for {user_id}")
                if app_callback:
                    app_callback.trigger_fast_forward()
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
                if app_callback:
                    app_callback.trigger_fast_forward()
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
                if app_callback:
                    app_callback.trigger_fast_forward()
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
                if app_callback:
                    app_callback.trigger_fast_forward()
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

            # Update client name to official name if resolved
            if app_callback:
                app_callback.start_client_timer(taxpayer_name, user_id)

            # AX Download
            try:
                download_and_rename(page, user_id, taxpayer_name, "AX", base_dir, app_callback)
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - AX download stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "AX_DOWNLOAD", vault_manager)
                logging.exception(f"AX download stage failed for {user_id}")

            # BX Download
            try:
                page.get_by_text("For your Information", exact=False).click()
                page.wait_for_timeout(2000)
                download_and_rename(page, user_id, taxpayer_name, "BX", base_dir, app_callback)
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
                download_and_rename(page, user_id, taxpayer_name, "AY", base_dir, app_callback)
            except Exception as e:
                print(f"🚨 [CRITICAL ERROR] - AY download stage failed for {user_id}.")
                capture_diagnostic_screenshot(page, user_id, "AY_DOWNLOAD", vault_manager)
                logging.exception(f"AY download stage failed for {user_id}")

            # BY Download
            try:
                page.get_by_text("For your Information", exact=False).click()
                page.wait_for_timeout(2000)
                download_and_rename(page, user_id, taxpayer_name, "BY", base_dir, app_callback)
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
            finally:
                if app_callback:
                    app_callback.trigger_fast_forward()

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
        return len(final_report)
    else:
        print("\n✅ [SUCCESS] - Comparison Complete. NO NEW NOTICES FOUND.")
        return 0


# ─────────────────────────────────────────────
# GUI APPLICATION
# ─────────────────────────────────────────────

# ── Premium Theme & Color Tokens ─────────────
BG_COLOR         = "#0E0E0E"  # Obsidian black background
SIDEBAR_BG       = "#1A1816"  # Dark charcoal left sidebar
CARD_BG          = "#151513"  # Main workspace card background
CARD_BORDER      = "#242220"  # Card border color
BORDER_COLOR     = "#242220"  # Dark divider
ACCENT_COLOR     = "#38BDF8"  # Sky Blue accent
ACCENT_HOVER     = "#0EA5E9"  # Hover accent
TEXT_PRIMARY     = "#EDEAE3"  # Eggshell white for primary
TEXT_SECONDARY   = "#6A6258"  # Muted secondary text
SUCCESS_COLOR    = "#4ADE80"  # Green
WARNING_COLOR    = "#FFB84D"  # Amber
DANGER_COLOR     = "#FF6B81"  # Rose


class App(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # ── Window Setup ─────────────────────
        self.title("Income Tax Notice Checker")
        self.geometry("1100x720")
        self.minsize(1000, 650)
        self.configure(fg_color=BG_COLOR)
        ctk.set_appearance_mode("dark")

        self._credentials_path = ""
        self._output_dir = ""
        self._running = False
        
        self._console_expanded = False  # Starts collapsed by default
        self._timer_active = False
        self._fast_forwarding = False

        self._build_ui()

        # Default paths (same folder as exe / script)
        default_creds = os.path.join(APP_DIR, "Credentials.xlsx")
        self._creds_entry.insert(0, default_creds)
        self._dir_entry.insert(0, APP_DIR)

    # ── UI Construction ──────────────────────

    def _build_ui(self):
        # ── Header Frame (Top Area) ──
        header = ctk.CTkFrame(self, fg_color="transparent", height=70)
        header.pack(fill="x", padx=30, pady=(20, 10))
        
        # Brand Block
        brand_frame = ctk.CTkFrame(header, fg_color="transparent")
        brand_frame.pack(side="left", fill="y")
        
        title_lbl = ctk.CTkLabel(
            brand_frame,
            text="💼  Income Tax Litigation Suite",
            font=("Sora", 16, "bold"),
            text_color=TEXT_PRIMARY,
            anchor="w"
        )
        title_lbl.pack(anchor="w")
        
        subtitle_lbl = ctk.CTkLabel(
            brand_frame,
            text="Notice Checker & Automated Reconciliation Engine",
            font=("JetBrains Mono", 10),
            text_color=TEXT_SECONDARY,
            anchor="w"
        )
        subtitle_lbl.pack(anchor="w", pady=(2, 0))
        
        # Horizontal subtle divider line below brand block (1px height)
        divider = ctk.CTkFrame(self, fg_color=BORDER_COLOR, height=1)
        divider.pack(fill="x", padx=30, pady=(0, 20))
        
        # ── Body Grid Container ──
        body_container = ctk.CTkFrame(self, fg_color="transparent")
        body_container.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        body_container.grid_columnconfigure(0, weight=0, minsize=280)
        body_container.grid_columnconfigure(1, weight=1)
        body_container.grid_rowconfigure(0, weight=1)
        
        # ── Left Column: Control Panel (Fixed ~280px) ──
        left_col = ctk.CTkFrame(body_container, fg_color=SIDEBAR_BG, border_width=1, border_color=CARD_BORDER, corner_radius=16, width=280)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        left_col.grid_propagate(False)
        
        # 1. Configuration Card
        config_card = ctk.CTkFrame(left_col, fg_color="transparent")
        config_card.pack(fill="x", pady=(10, 10))
        
        # Credentials File
        creds_title = ctk.CTkLabel(
            config_card,
            text="Credentials Registry (.xlsx)",
            font=("JetBrains Mono", 11),
            text_color=TEXT_SECONDARY,
            anchor="w"
        )
        creds_title.pack(fill="x", padx=20, pady=(15, 5))
        
        creds_row = ctk.CTkFrame(config_card, fg_color="transparent")
        creds_row.pack(fill="x", padx=20, pady=(0, 15))
        
        self._creds_entry = ctk.CTkEntry(
            creds_row,
            font=("JetBrains Mono", 11),
            text_color=TEXT_PRIMARY,
            fg_color="#0A0A0A",
            border_color=CARD_BORDER,
            corner_radius=8,
            height=32
        )
        self._creds_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self._creds_browse_btn = ctk.CTkButton(
            creds_row,
            text="Browse…",
            font=("Sora", 11, "bold"),
            text_color="#0E0E0E",
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            width=70,
            height=32,
            corner_radius=8,
            command=self._pick_credentials
        )
        self._creds_browse_btn.pack(side="right")
        
        # Output Directory
        dir_title = ctk.CTkLabel(
            config_card,
            text="Destination Folder (Saved Files & Reports)",
            font=("JetBrains Mono", 11),
            text_color=TEXT_SECONDARY,
            anchor="w"
        )
        dir_title.pack(fill="x", padx=20, pady=(5, 5))
        
        dir_row = ctk.CTkFrame(config_card, fg_color="transparent")
        dir_row.pack(fill="x", padx=20, pady=(0, 20))
        
        self._dir_entry = ctk.CTkEntry(
            dir_row,
            font=("JetBrains Mono", 11),
            text_color=TEXT_PRIMARY,
            fg_color="#0A0A0A",
            border_color=CARD_BORDER,
            corner_radius=8,
            height=32
        )
        self._dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self._dir_browse_btn = ctk.CTkButton(
            dir_row,
            text="Browse…",
            font=("Sora", 11, "bold"),
            text_color="#0E0E0E",
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            width=70,
            height=32,
            corner_radius=8,
            command=self._pick_folder
        )
        self._dir_browse_btn.pack(side="right")
        
        # 2. Run Engine Card
        run_card = ctk.CTkFrame(left_col, fg_color="transparent")
        run_card.pack(fill="x")
        
        self._start_btn = ctk.CTkButton(
            run_card,
            text="▶ Start Notice Check",
            font=("Sora", 12, "bold"),
            text_color="#0E0E0E",
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER,
            height=46,
            corner_radius=12,
            command=self._on_start
        )
        self._start_btn.pack(fill="x", padx=20, pady=(0, 15))
        
        # Status Badge Frame
        status_row = ctk.CTkFrame(run_card, fg_color="transparent")
        status_row.pack(fill="x", padx=20, pady=(0, 20))
        
        status_lbl = ctk.CTkLabel(
            status_row,
            text="Engine Status:",
            font=("JetBrains Mono", 11),
            text_color=TEXT_SECONDARY,
            anchor="w"
        )
        status_lbl.pack(side="left")
        
        self._status_badge = ctk.CTkLabel(
            status_row,
            text="• Idle",
            font=("JetBrains Mono", 11, "bold"),
            text_color=TEXT_SECONDARY,
            anchor="w"
        )
        self._status_badge.pack(side="left", padx=10)
        
        # ── Right Column: Tracking & Diagnostics (Fluid Weight 1) ──
        self._right_col = ctk.CTkFrame(body_container, fg_color="transparent")
        self._right_col.grid(row=0, column=1, sticky="nsew")
        self._right_col.grid_columnconfigure(0, weight=1)
        
        self._right_col.grid_rowconfigure(0, weight=0)
        self._right_col.grid_rowconfigure(1, weight=0)
        self._right_col.grid_rowconfigure(2, weight=1)
        self._right_col.grid_rowconfigure(3, weight=0)
        
        # 0. Master Reconciliation Card (Completion banner - gridded by default)
        self._reconciliation_card = ctk.CTkFrame(self._right_col, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=16)
        self._reconciliation_card.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        
        self._recon_label = ctk.CTkLabel(
            self._reconciliation_card,
            text="✨ Workspace Check Completed. 0 New Notices / Updates flagged.",
            font=("Instrument Sans", 12, "bold"),
            text_color=TEXT_PRIMARY,
            anchor="w"
        )
        self._recon_label.pack(side="left", padx=20, pady=15, fill="x", expand=True)
        
        open_report_btn = ctk.CTkButton(
            self._reconciliation_card,
            text="📂 Open Flagged Notice Report (Excel)",
            font=("Sora", 11, "bold"),
            text_color=ACCENT_COLOR,
            fg_color="transparent",
            border_width=1,
            border_color=ACCENT_COLOR,
            hover_color=CARD_BORDER,
            corner_radius=8,
            height=36,
            command=self._open_flagged_report
        )
        open_report_btn.pack(side="right", padx=20, pady=15)
        
        # 1. Active Client Visual Tracker Card
        tracker_card = ctk.CTkFrame(self._right_col, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=16)
        tracker_card.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        
        self._client_label = ctk.CTkLabel(
            tracker_card,
            text="🏢 Scanning Account: [Finished]",
            font=("Sora", 13, "bold"),
            text_color=TEXT_PRIMARY,
            anchor="w"
        )
        self._client_label.pack(fill="x", padx=20, pady=(15, 5))
        
        progress_row = ctk.CTkFrame(tracker_card, fg_color="transparent")
        progress_row.pack(fill="x", padx=20, pady=(0, 15))
        
        self._progress_bar = ctk.CTkProgressBar(
            progress_row,
            progress_color="#14B8A6", # Teal color
            fg_color="#100E0D",
            height=6,
            corner_radius=3
        )
        self._progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self._progress_bar.set(0.01) # Set to 0.01 to show a single teal dot!
        
        self._timer_label = ctk.CTkLabel(
            progress_row,
            text="Estimated remaining: --",
            font=("JetBrains Mono", 10),
            text_color=TEXT_SECONDARY,
            width=200,
            anchor="e"
        )
        self._timer_label.pack(side="right")
        
        # 2. Real-Time CSV Download Ledger Card
        ledger_card = ctk.CTkFrame(self._right_col, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=16)
        ledger_card.grid(row=2, column=0, sticky="nsew", pady=(0, 20))
        
        ledger_title = ctk.CTkLabel(
            ledger_card,
            text="R E A L - T I M E   C S V   D O W N L O A D   L E D G E R",
            font=("JetBrains Mono", 11, "bold"),
            text_color=TEXT_PRIMARY,
            anchor="w"
        )
        ledger_title.pack(fill="x", padx=20, pady=(15, 5))
        
        self._ledger_frame = ctk.CTkScrollableFrame(
            ledger_card,
            fg_color="#100E0D",
            corner_radius=12
        )
        self._ledger_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        # 3. Collapsible Deep Diagnostics Console Card
        self._console_card = ctk.CTkFrame(self._right_col, fg_color=CARD_BG, border_width=1, border_color=CARD_BORDER, corner_radius=16)
        self._console_card.grid(row=3, column=0, sticky="ew")
        
        self._console_toggle_btn = ctk.CTkButton(
            self._console_card,
            text="▶   Detailed System Logs (Technical Diagnostics)",
            font=("JetBrains Mono", 11, "bold"),
            text_color=TEXT_PRIMARY,
            fg_color="transparent",
            hover=False,
            anchor="w",
            height=40,
            command=self._toggle_console
        )
        self._console_toggle_btn.pack(fill="x", padx=15, pady=5)
        
        # Log Box (starts unpacked/collapsed)
        self._log_box = ctk.CTkTextbox(
            self._console_card,
            fg_color="#060606",
            text_color=TEXT_PRIMARY,
            font=("JetBrains Mono", 10),
            corner_radius=8,
            state="disabled",
            wrap="word",
            height=130
        )

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
            self._creds_entry.delete(0, END)
            self._creds_entry.insert(0, path)

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self._dir_entry.delete(0, END)
            self._dir_entry.insert(0, path)

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

    def _toggle_console(self):
        if self._console_expanded:
            self._log_box.pack_forget()
            self._console_toggle_btn.configure(text="▶   Detailed System Logs (Technical Diagnostics)")
            self._console_expanded = False
        else:
            self._log_box.pack(fill="x", padx=20, pady=(0, 15))
            self._console_toggle_btn.configure(text="▼   Detailed System Logs (Technical Diagnostics)")
            self._console_expanded = True

    # ── Master Reconciliation Actions ────────

    def show_reconciliation_card(self, flagged_count):
        self.after(0, self._ui_show_reconciliation_card, flagged_count)

    def _ui_show_reconciliation_card(self, flagged_count):
        # Play non-intrusive sound effect
        try:
            import winsound
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            try:
                sys.stdout.write('\a')
                sys.stdout.flush()
            except Exception:
                pass

        # Update summary text
        self._recon_label.configure(text=f"✨ Workspace Check Completed. {flagged_count} New Notices / Updates flagged.")
        
        # Grid it at the very top of the right column (row=0)
        self._reconciliation_card.grid(row=0, column=0, sticky="ew", pady=(0, 20))

    def hide_reconciliation_card(self):
        self._reconciliation_card.grid_forget()

    def _open_flagged_report(self):
        file_path = os.path.join(self._output_dir, "New_Notices_Flagged_Report.xlsx")
        if os.path.exists(file_path):
            if sys.platform == "win32":
                os.startfile(file_path)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                import subprocess
                subprocess.call([opener, file_path])
        else:
            self._log("⚠️ Flagged notices report does not exist yet.")

    # ── Interactive Client Tracking & Timer ──

    def start_client_timer(self, name, pan):
        self.after(0, self._ui_start_client_timer, name, pan)

    def _ui_start_client_timer(self, name, pan):
        self._timer_active = True
        self._timer_seconds_remaining = 20.0
        self._fast_forwarding = False
        
        self._client_label.configure(text=f"🏢 Scanning Account: {name} ({pan})")
        self._progress_bar.set(0.01)
        self._timer_label.configure(text="Estimated remaining: 20s")
        
        # Launch tick loop
        self._tick_timer()

    def _tick_timer(self):
        if not self._timer_active or self._fast_forwarding:
            return
            
        self._timer_seconds_remaining -= 0.1
        if self._timer_seconds_remaining <= 0:
            self._timer_seconds_remaining = 0
            self._progress_bar.set(1.0)
            self._timer_label.configure(text="Estimated remaining: 0s")
            self._timer_active = False
        else:
            progress = max(0.01, (20.0 - self._timer_seconds_remaining) / 20.0)
            self._progress_bar.set(progress)
            self._timer_label.configure(text=f"Estimated remaining: {int(self._timer_seconds_remaining)}s")
            # Schedule next 100ms tick
            self.after(100, self._tick_timer)

    def trigger_fast_forward(self):
        self.after(0, self._ui_trigger_fast_forward)

    def _ui_trigger_fast_forward(self):
        if not self._timer_active:
            self._progress_bar.set(1.0)
            self._timer_label.configure(text="Estimated remaining: 0s")
            return
            
        self._fast_forwarding = True
        self._animate_fast_forward()

    def _animate_fast_forward(self):
        current_progress = self._progress_bar.get()
        if current_progress >= 1.0:
            self._progress_bar.set(1.0)
            self._timer_label.configure(text="Estimated remaining: 0s")
            self._timer_active = False
            self._fast_forwarding = False
        else:
            new_progress = min(1.0, current_progress + 0.1)
            self._progress_bar.set(new_progress)
            remaining_pct = 1.0 - new_progress
            rem_secs = max(0, int(self._timer_seconds_remaining * remaining_pct))
            self._timer_label.configure(text=f"Estimated remaining: {rem_secs}s")
            self.after(15, self._animate_fast_forward)

    # ── Real-Time Ledger Operations ──────────

    def add_ledger_entry(self, file_id, filename, status_text, size_str, status_type="success"):
        self.after(0, self._ui_add_ledger_entry, file_id, filename, status_text, size_str, status_type)

    def _ui_add_ledger_entry(self, file_id, filename, status_text, size_str, status_type):
        # Create a container frame for this row
        row_frame = ctk.CTkFrame(self._ledger_frame, fg_color="transparent")
        row_frame.pack(fill="x", pady=4, padx=5)
        
        # Mapping file_id to pool name
        if file_id == "AX":
            pool_text = "AX Notice Pool"
        elif file_id == "BX":
            pool_text = "BX Notice Pool"
        elif file_id == "AY":
            pool_text = "AY External"
        elif file_id == "BY":
            pool_text = "BY External"
        else:
            pool_text = f"{file_id} Pool"
            
        pool_label_str = f"[📁 {pool_text:<14}]"
        
        # Color coding for state
        if status_type == "success":
            bullet_icon = "•"
            status_color = SUCCESS_COLOR
        elif status_type == "warning":
            bullet_icon = "•"
            status_color = WARNING_COLOR
        else:
            bullet_icon = "•"
            status_color = DANGER_COLOR
            
        # File ID label
        fid_label = ctk.CTkLabel(
            row_frame,
            text=pool_label_str,
            font=("JetBrains Mono", 11, "bold"),
            text_color=TEXT_PRIMARY,
            anchor="w"
        )
        fid_label.pack(side="left", padx=(5, 10))
        
        # Filename label
        fn_label = ctk.CTkLabel(
            row_frame,
            text=filename,
            font=("JetBrains Mono", 11),
            text_color=TEXT_SECONDARY,
            anchor="w"
        )
        fn_label.pack(side="left", fill="x", expand=True, padx=5)
        
        # Status label
        stat_label = ctk.CTkLabel(
            row_frame,
            text=f"{bullet_icon} {status_text}",
            font=("JetBrains Mono", 11, "bold"),
            text_color=status_color,
            anchor="w",
            width=160
        )
        stat_label.pack(side="left", padx=10)
        
        # Size label
        sz_label = ctk.CTkLabel(
            row_frame,
            text=size_str,
            font=("JetBrains Mono", 11),
            text_color=TEXT_SECONDARY,
            anchor="e",
            width=80
        )
        sz_label.pack(side="right", padx=(5, 5))

    # ── Run Logic ────────────────────────────

    def _on_start(self):
        if self._running:
            return

        creds_path = self._creds_entry.get().strip()
        output_dir = self._dir_entry.get().strip()

        if not creds_path or not os.path.isfile(creds_path):
            self._log("❌ Please select a valid Credentials Excel file first.")
            return

        if not output_dir or not os.path.isdir(output_dir):
            self._log("❌ Please select a valid output folder first.")
            return

        self._credentials_path = creds_path
        self._output_dir = output_dir
        self._running = True

        # Clear previous ledger rows
        for child in self._ledger_frame.winfo_children():
            child.destroy()
            
        # Hide reconciliation card
        self.hide_reconciliation_card()

        # Disable inputs and buttons
        self._creds_browse_btn.configure(state="disabled")
        self._dir_browse_btn.configure(state="disabled")
        self._creds_entry.configure(state="disabled")
        self._dir_entry.configure(state="disabled")
        self._start_btn.configure(state="disabled", fg_color="#2E2A27", text="⏳ Running Notice Sync...")
        self._set_status("• Syncing Browser...", WARNING_COLOR)

        # Clear log box
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
                self.after(0, self._on_finished, False, 0)
                return

            self.after(0, self._set_status, "• Crawling Portal...", ACCENT_COLOR)

            # 3. Input Validation
            print("ℹ️ [INFO]  - Validating credentials file schema...")
            is_valid, err_layout = validate_credentials_file(creds)
            if not is_valid:
                print(err_layout)
                logging.error(f"Credentials validation failed:\n{err_layout}")
                self.after(0, self._on_finished, False, 0)
                return
            print("✅ [SUCCESS] - Credentials file schema validated successfully!")

            # 4. Main Automation Flow
            successful_pans = run_multi_client_downloads(creds, base_dir, vault_mgr, app_callback=self)
            flagged_count = process_and_flag(successful_pans, base_dir, output_report)

            print("\n✅ [SUCCESS] - ALL DONE — Notice check complete!")
            self.after(0, self._on_finished, True, flagged_count)
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
            
            self.after(0, self._on_finished, False, 0)
        finally:
            sys.stdout = self._old_stdout

    def _on_finished(self, success, flagged_count=0):
        self._running = False
        
        # Re-enable inputs and buttons
        self._creds_browse_btn.configure(state="normal")
        self._dir_browse_btn.configure(state="normal")
        self._creds_entry.configure(state="normal")
        self._dir_entry.configure(state="normal")
        self._start_btn.configure(state="normal", fg_color=ACCENT_COLOR, text="▶ Start Notice Check")
        
        # Reset active client visual tracker UI
        self._timer_active = False
        self._progress_bar.set(0.01)
        self._client_label.configure(text="🏢 Scanning Account: [Finished]")
        self._timer_label.configure(text="Estimated remaining: --")
        
        if success:
            self._set_status("• Done ✓", SUCCESS_COLOR)
            self.show_reconciliation_card(flagged_count)
        else:
            self._set_status("• Error ❌", DANGER_COLOR)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
