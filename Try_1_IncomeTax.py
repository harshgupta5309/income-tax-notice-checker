import os
import sys

# Determine if the application is running as a compiled PyInstaller binary
if getattr(sys, 'frozen', False):
    # Directory of the compiled standalone .exe
    APP_DIR = os.path.dirname(sys.executable)
    # PyInstaller temporary extraction folder containing bundled assets
    HTML_PATH = os.path.join(sys._MEIPASS, "code.html")
else:
    # Running in a standard local python interpreter
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    HTML_PATH = os.path.join(APP_DIR, "code.html")

# Enforce our dynamic portable root output directories
BASE_DIR = os.path.join(APP_DIR, "Income_tax_folder")
os.makedirs(BASE_DIR, exist_ok=True)

# Force Playwright's browser context to remain entirely inside a local subfolder
# This prevents the app from needing admin rights to write to %LOCALAPPDATA%
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(APP_DIR, "ms-playwright")

import glob
import shutil
import logging
import pyzipper
import ctypes
import re
from io import StringIO
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# ─────────────────────────────────────────────
# CONFIGURATION & PORTABLE PATH RESOLUTION
# ─────────────────────────────────────────────
OUTPUT_REPORT = os.path.join(BASE_DIR, "New_Notices_Flagged_Report.xlsx")
CREDENTIALS_FILE = os.path.join(APP_DIR, "Credentials.xlsx")
ABORT_SIGNAL = False



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
            ctypes.windll.kernel32.SetFileAttributesW(path, 0x02 | 0x04)
        except Exception:
            try:
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
    return True, None


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


# --- CUSTOM EXCEPTIONS FOR USER DECISIONS ---

class SkipClientException(Exception):
    """Custom exception raised when the user decides to skip the current client due to delay"""
    pass

class StopPipelineException(Exception):
    """Custom exception raised when the user decides to stop the automation run entirely"""
    pass

def is_abort_requested(api_ref=None):
    if globals().get('ABORT_SIGNAL', False):
        return True
    if api_ref and getattr(api_ref, 'abort_requested', False):
        return True
    return False

def robust_wait_for_selector(page, selector, state="visible", timeout_sec=20, pan="", api_ref=None):
    """Waits for a selector, and if it fails within timeout_sec, prompts the user via PyWebView API"""
    start_time = datetime.now()
    while True:
        if is_abort_requested(api_ref):
            raise StopPipelineException()
            
        try:
            page.wait_for_selector(selector, state=state, timeout=1000)
            return True
        except Exception as e:
            if is_abort_requested(api_ref):
                raise StopPipelineException()
                
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed >= timeout_sec:
                if api_ref:
                    print(f"⏳ Selector '{selector}' not loaded within {timeout_sec} seconds. Prompting user...")
                    decision = api_ref.prompt_user_server_delay(pan, selector)
                    if decision == 'wait':
                        print("User requested to WAIT. Retrying wait for 30 seconds...")
                        timeout_sec = 30
                        start_time = datetime.now()
                        continue
                    elif decision == 'skip':
                        print("User requested to SKIP this client.")
                        raise SkipClientException()
                    elif decision == 'stop':
                        print("User requested to STOP the automation pipeline.")
                        raise StopPipelineException()
                raise e

def robust_wait_for_locator(locator, state="visible", timeout_sec=20, pan="", api_ref=None):
    """Waits for a Playwright locator, and if it fails, prompts the user"""
    start_time = datetime.now()
    while True:
        if is_abort_requested(api_ref):
            raise StopPipelineException()
            
        try:
            locator.wait_for(state=state, timeout=1000)
            return True
        except Exception as e:
            if is_abort_requested(api_ref):
                raise StopPipelineException()
                
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed >= timeout_sec:
                if api_ref:
                    print(f"⏳ Locator not loaded within {timeout_sec} seconds. Prompting user...")
                    decision = api_ref.prompt_user_server_delay(pan, "Element Load")
                    if decision == 'wait':
                        print("User requested to WAIT. Retrying wait for 30 seconds...")
                        timeout_sec = 30
                        start_time = datetime.now()
                        continue
                    elif decision == 'skip':
                        print("User requested to SKIP this client.")
                        raise SkipClientException()
                    elif decision == 'stop':
                        print("User requested to STOP the automation pipeline.")
                        raise StopPipelineException()
                raise e

# --- HELPER FUNCTIONS ---

def download_and_rename(page, pan, name, file_id):
    """Handles the CSV download and renaming process"""
    print(f"ℹ️ [INFO]  - Triggering download for ID: {file_id}...")
    download_selector = "button.downloadButtonsec"
    
    try:
        with page.expect_download(timeout=60000) as download_info:
            page.locator(download_selector).first.click()
        
        download = download_info.value
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = "".join(x for x in name if x.isalnum() or x in " -_").strip()
        filename = f"{safe_name}_{pan}_{file_id}_{timestamp}.csv"
        save_path = os.path.join(BASE_DIR, filename)
        
        download.save_as(save_path)
        print(f"✅ [SUCCESS] - Successfully saved: {filename}")
        return True
    except Exception as e:
        print(f"⚠️ [WARNING] - Failed to download {file_id}: {e}")
def get_latest_and_prev_files(pan, file_id):
    """Finds the two most recent CSV files for comparison"""
    search_pattern = os.path.join(BASE_DIR, f"*_{pan}_{file_id}_*.csv")
    files = glob.glob(search_pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    
    if len(files) >= 2:
        return files[0], files[1] 
    elif len(files) == 1:
        return files[0], None
    return None, None

# --- MAIN AUTOMATION LOGIC ---

def run_multi_client_downloads(vault_manager=None, api_ref=None):
    if vault_manager is None:
        vault_manager = SecureVaultManager(BASE_DIR)
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)

    try:
        df_creds = pd.read_excel(CREDENTIALS_FILE)
        df_creds.columns = df_creds.columns.str.strip()
        print(f"ℹ️ [INFO]  - Loaded {len(df_creds)} clients from credentials file.")
    except Exception as e:
        print(f"🚨 [CRITICAL ERROR] - Could not read credentials file. {e}")
        logging.exception("Could not read credentials file")
        return []

    processed_pans = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-position=-2000,-2000", "--window-size=1920,1080"])
        
        try:
            for index, row in df_creds.iterrows():
                # Check abort signal before starting a client
                if is_abort_requested(api_ref):
                    print("\n🛑 [ABORT] - Abort signal received. Terminating loop...")
                    break
                    
                user_id = str(row['Login_ID']).strip()
                password = str(row['Password']).strip()
                
                print(f"\n{'=' * 50}")
                print(f"🏢 STARTING CLIENT: {user_id}")
                print(f"{'=' * 50}")
                print("🔑 [STAGE-AUTH] - 0% - Portal launched / loading")

                # Create a fresh browser context and page for this client
                context = browser.new_context(viewport={'width': 1920, 'height': 1080})
                context.set_default_timeout(30000)
                context.set_default_navigation_timeout(30000)
                page = context.new_page()
                
                # Apply stealth sync to the fresh page
                from playwright_stealth import stealth_sync
                stealth_sync(page)

                try:
                    print("\nℹ️ [INFO]  - Launching Income Tax Portal...")
                    try:
                        page.goto("https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en", wait_until="networkidle", timeout=45000)
                    except Exception as e:
                        print(f"⚠️ [WARNING] - Navigation to portal timed out: {e}. Attempting recovery...")

                    print(f"ℹ️ [INFO]  - Scanning for login screen for {user_id}...")
                    
                    try:
                        robust_wait_for_selector(page, "#panAdhaarUserId", state="visible", timeout_sec=20, pan=user_id, api_ref=api_ref)
                        print("✅ [SUCCESS] - Portal loaded! Injecting credentials...")
                    except (SkipClientException, StopPipelineException) as e:
                        raise e
                    except Exception:
                        print(f"🚨 [CRITICAL ERROR] - Portal seems completely down or stuck. Skipping {user_id}.")
                        logging.error(f"Portal down/stuck when scanning login screen for {user_id}")
                        continue
                    
                    # Stage 1: Login Form Injection
                    try:
                        page.locator("#panAdhaarUserId").click(force=True)
                        page.locator("#panAdhaarUserId").fill("")
                        page.locator("#panAdhaarUserId").press_sequentially(user_id, delay=100)
                        page.wait_for_timeout(1000)
                        page.locator("#panAdhaarUserId").press("Tab")
                        page.wait_for_timeout(500)
                        page.locator('button.large-button-primary:has-text("Continue")').first.click(force=True)
                        print("🔑 [STAGE-AUTH] - 25% - User ID Entered and Continue Clicked")
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - Login form injection stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "LOGIN_INJECT", vault_manager)
                        logging.exception(f"Login ID injection failed for {user_id}")
                        continue

                    # Stage 2: OTP/Password Navigation
                    try:
                        robust_wait_for_selector(page, "#passwordCheckBox-input", timeout_sec=20, pan=user_id, api_ref=api_ref)
                        try:
                            # Click input directly without strict synchronous check assertion
                            page.locator("#passwordCheckBox-input").click(force=True, timeout=5000)
                        except Exception:
                            try:
                                # Fallback to clicking label
                                page.locator("label[for='passwordCheckBox-input']").click(timeout=5000)
                            except Exception:
                                # Standard check fallback
                                page.check("#passwordCheckBox-input", force=True)
                        page.fill("#loginPasswordField", password)
                        page.keyboard.press("Tab")
                        print("🔑 [STAGE-AUTH] - 50% - Password Entered and Login Clicked")
                    except (SkipClientException, StopPipelineException) as e:
                        raise e
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
                            if is_abort_requested(api_ref):
                                raise StopPipelineException()
                            if "/dashboard" in page.url.lower():
                                login_success = True
                                break
                            attempt += 1
                            
                            dual_login_btn = page.get_by_role("button", name="Login Here")
                            if dual_login_btn.is_visible(timeout=2000):
                                dual_login_btn.click()
                                page.wait_for_timeout(3000)
                                continue
                            
                            login_btn = page.locator('button.marTop26')
                            if login_btn.is_visible(timeout=2000):
                                login_btn.click(force=True)
                                page.wait_for_timeout(4000)

                        if not login_success:
                            raise Exception("Dashboard not loaded after 10 attempts.")
                        print("🔑 [STAGE-AUTH] - 75% - Logged in to Income Tax Portal dashboard")
                    except (SkipClientException, StopPipelineException) as e:
                        raise e
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - Login authentication stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "LOGIN_AUTH", vault_manager)
                        logging.exception(f"Login authentication failed for {user_id}")
                        continue

                    # Stage 4: Navigating to e-Proceedings
                    try:
                        print(f"ℹ️ [INFO]  - Navigating to e-Proceedings for {user_id}...")
                        page.wait_for_load_state("networkidle")
                        robust_wait_for_locator(page.locator('[id="Pending Actions"]'), state="visible", timeout_sec=20, pan=user_id, api_ref=api_ref)
                        page.locator('[id="Pending Actions"]').click(force=True)
                        
                        try:
                            page.locator('role=menuitem[name="e-Proceedings"]').wait_for(state="visible", timeout=5000)
                            page.locator('role=menuitem[name="e-Proceedings"]').click()
                        except Exception:
                            page.get_by_text("e-Proceedings", exact=True).click()
                            
                        page.wait_for_load_state("networkidle")
                        print("🔑 [STAGE-AUTH] - 100% - Portal loaded and Eproceedings Page has been opened")
                    except (SkipClientException, StopPipelineException) as e:
                        raise e
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - Navigating to e-Proceedings stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "EPROC_NAV", vault_manager)
                        logging.exception(f"e-Proceedings navigation failed for {user_id}")
                        continue

                    # Directly read name from sheet as requested to bypass slow name-scraping checks
                    taxpayer_name = str(row['Name']).strip() if (pd.notna(row.get('Name')) and str(row.get('Name')).strip()) else "Taxpayer"

                    print(f"👤 CLIENT_INFO: {user_id} | {taxpayer_name}")

                    if is_abort_requested(api_ref):
                        raise StopPipelineException()
                    # AX Download
                    try:
                        download_and_rename(page, user_id, taxpayer_name, "AX")
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - AX download stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "AX_DOWNLOAD", vault_manager)
                        logging.exception(f"AX download stage failed for {user_id}")
                    print("📥 [STAGE-EXTRACTION] - 25% - AX File downloaded")
                    
                    if is_abort_requested(api_ref):
                        raise StopPipelineException()
                    # BX Download
                    try:
                        page.get_by_text("For your Information", exact=False).click()
                        page.wait_for_timeout(2000)
                        download_and_rename(page, user_id, taxpayer_name, "BX")
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - BX download stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "BX_DOWNLOAD", vault_manager)
                        logging.exception(f"BX download stage failed for {user_id}")
                    print("📥 [STAGE-EXTRACTION] - 50% - BX File downloaded")
                    
                    if is_abort_requested(api_ref):
                        raise StopPipelineException()
                    # AY Download
                    try:
                        page.locator('span.mat-button-toggle-label-content:has-text("Of Other PAN/TAN")').click()
                        page.wait_for_timeout(3000)
                        download_and_rename(page, user_id, taxpayer_name, "AY")
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - AY download stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "AY_DOWNLOAD", vault_manager)
                        logging.exception(f"AY download stage failed for {user_id}")
                    print("📥 [STAGE-EXTRACTION] - 75% - AY File downloaded")
                    
                    if is_abort_requested(api_ref):
                        raise StopPipelineException()
                    # BY Download
                    try:
                        page.get_by_text("For your Information", exact=False).click()
                        page.wait_for_timeout(2000)
                        download_and_rename(page, user_id, taxpayer_name, "BY")
                    except Exception as e:
                        print(f"🚨 [CRITICAL ERROR] - BY download stage failed for {user_id}.")
                        capture_diagnostic_screenshot(page, user_id, "BY_DOWNLOAD", vault_manager)
                        logging.exception(f"BY download stage failed for {user_id}")

                    processed_pans.append(user_id)
                    print(f"📥 [STAGE-EXTRACTION] - 100% - All files downloaded successfully for client: {user_id}")

                except SkipClientException:
                    try:
                        page.goto("https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en", timeout=15000)
                    except Exception:
                        pass
                    continue

        except StopPipelineException:
            print("\n🛑 [STOP] - Synchronization stopped by user request. Exiting loop...")

        print("\nAll clients processed. Closing browser...")
        browser.close()
        
    return processed_pans
        
    return processed_pans

# --- PANDAS COMPARISON LOGIC ---

def load_portal_csv(filepath):
    """
    Bulletproof CSV loader for Income Tax Portal notices.
    Handles:
    - Empty files (0 bytes) -> returns empty DataFrame
    - 'No Records Found' text -> returns empty DataFrame
    - Leading/trailing whitespaces in headers -> strips them
    - Dynamic header detection: finds the row containing "Proceeding Name" or "Notice DIN" and uses it as header.
    - Cleans whitespace and formula wrappers like ="DIN_NUMBER"
    """
    if not filepath or not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return pd.DataFrame()
        
    try:
        # Read lines raw first to detect header index and check for "No Records Found"
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            raw_lines = [line.strip() for line in f]
            
        # Remove completely empty lines
        non_empty_lines = [line for line in raw_lines if line]
        
        if not non_empty_lines:
            return pd.DataFrame()
            
        # Check for 'No Records Found' in the first 3 non-empty lines
        for line in non_empty_lines[:3]:
            if "no records" in line.lower() or "no records found" in line.lower():
                return pd.DataFrame()
                
        # Dynamic header detection
        header_idx = -1
        for idx, line in enumerate(non_empty_lines[:5]):
            line_upper = line.upper()
            if "PROCEEDING" in line_upper or "NOTICE DIN" in line_upper or "DIN" in line_upper:
                header_idx = raw_lines.index(line)
                break
                
        if header_idx == -1:
            header_idx = 0
            
        df = pd.read_csv(filepath, skiprows=header_idx)
        
        # Strip whitespace from headers
        df.columns = [str(c).strip() for c in df.columns]
        
        # Clean cell values
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].fillna("").astype(str).str.strip()
                # Remove Excel formula wrappers like ="value"
                df[col] = df[col].str.replace(r'^="([^"]*)"$', r'\1', regex=True).str.strip()
                # Clean 'null' and 'nan' representations to actual empty strings
                df[col] = df[col].replace({'null': '', 'nan': '', 'NaN': '', 'None': ''})
                
        # Drop rows where all elements are empty or NaN
        df = df.dropna(how='all')
        if not df.empty:
            non_empty_mask = df.apply(lambda row: row.astype(str).str.strip().str.len() > 0).any(axis=1)
            df = df[non_empty_mask].reset_index(drop=True)
        
        return df
    except Exception as e:
        print(f"⚠️ Error loading CSV {filepath}: {e}")
        return pd.DataFrame()

def find_din_column(df):
    if df.empty or len(df.columns) == 0:
        return None
    # 1. Search for exact word matches in columns
    for col in df.columns:
        col_words = "".join(c if c.isalnum() else " " for c in str(col).upper()).split()
        if 'DIN' in col_words or 'ID' in col_words or 'REFERENCE' in col_words: 
            return col
    # 2. Fall back to substring match
    for col in df.columns:
        col_upper = str(col).upper()
        if 'DIN' in col_upper or 'REFERENCE' in col_upper:
            return col
    return None

def extract_col_data(df, keywords):
    if df.empty or len(df.columns) == 0:
        return pd.Series([], dtype=str)
        
    for col in df.columns:
        col_lower = str(col).lower().strip()
        col_words = "".join(c if c.isalnum() else " " for c in col_lower).split()
        
        if any(k in col_lower for k in keywords if len(k) > 3) or any(k in col_words for k in keywords if len(k) <= 3):
            return df[col].fillna("").astype(str).str.strip().reset_index(drop=True)
            
    return pd.Series([""] * len(df), dtype=str)

def process_and_flag(pan_list):
    if not pan_list:
        print("⚠️ [WARNING] - No valid PANs processed. Skipping comparison.")
        return

    print("ℹ️ [INFO]  - Starting strict template mapping (high-assurance)...")

    all_new_notices = []
    
    for pan in pan_list:
        for fid in ['AX', 'BX', 'AY', 'BY']:
            new_file, old_file = get_latest_and_prev_files(pan, fid)
            if not new_file: 
                continue

            try:
                # Load new file
                df_new = load_portal_csv(new_file)
                if df_new.empty:
                    if os.path.exists(new_file):
                        print(f"⚠️ [WARNING] - File {fid} for {pan} has no active rows (No Records Found). Skipping.")
                    continue
                    
                # Load old file if it exists, else empty
                if old_file:
                    df_old = load_portal_csv(old_file)
                else:
                    df_old = pd.DataFrame(columns=df_new.columns)

                # Map new and old to standardized template
                def map_to_template(df, file_id, client_pan):
                    if df.empty:
                        return pd.DataFrame()
                        
                    mapped = pd.DataFrame()
                    mapped['Proceeding Name'] = extract_col_data(df, ['proceeding name'])
                    mapped['PAN'] = client_pan
                    mapped['AY'] = extract_col_data(df, ['ay', 'assessment year'])
                    mapped['TY'] = extract_col_data(df, ['ty', 'financial year'])
                    mapped['Proceeding Limitation Date'] = extract_col_data(df, ['limitation date'])
                    mapped['Proceeding Status'] = extract_col_data(df, ['status'])
                    
                    if file_id in ['BX', 'BY']:
                        mapped['Proceeding concluded date'] = extract_col_data(df, ['concluded date'])
                    else:
                        mapped['Proceeding concluded date'] = "" 
                        
                    # Extract DIN raw
                    din_col_name = find_din_column(df)
                    if din_col_name and din_col_name in df.columns:
                        mapped['Notice DIN'] = df[din_col_name].fillna("").astype(str).str.strip()
                        mapped['Notice DIN'] = mapped['Notice DIN'].str.replace(r'^="([^"]*)"$', r'\1', regex=True).str.strip()
                        mapped['Notice DIN'] = mapped['Notice DIN'].replace({'null': '', 'nan': '', 'None': ''})
                    else:
                        mapped['Notice DIN'] = ""
                        
                    mapped['Notice Sent Date'] = extract_col_data(df, ['sent date', 'issued on', 'date of issue'])
                    mapped['Notice Section'] = extract_col_data(df, ['section'])
                    mapped['Date of Compliance'] = extract_col_data(df, ['compliance', 'due date'])
                    mapped['Date Response submitted(Last Response Submitted)'] = extract_col_data(df, ['response submitted'])
                    
                    # Clean all fields
                    for col in mapped.columns:
                        mapped[col] = mapped[col].fillna("").astype(str).str.strip()
                        mapped[col] = mapped[col].replace({'null': '', 'nan': '', 'None': ''})
                        
                    return mapped

                df_new_mapped = map_to_template(df_new, fid, pan)
                df_old_mapped = map_to_template(df_old, fid, pan) if not df_old.empty else pd.DataFrame(columns=df_new_mapped.columns)

                if df_new_mapped.empty:
                    continue

                # Filter out obvious ghost rows
                df_new_mapped = df_new_mapped[
                    (df_new_mapped['Proceeding Name'] != "") | 
                    (df_new_mapped['Notice DIN'] != "") | 
                    (df_new_mapped['Notice Sent Date'] != "")
                ].reset_index(drop=True)

                if df_new_mapped.empty:
                    continue

                if not df_old_mapped.empty:
                    df_old_mapped = df_old_mapped[
                        (df_old_mapped['Proceeding Name'] != "") | 
                        (df_old_mapped['Notice DIN'] != "") | 
                        (df_old_mapped['Notice Sent Date'] != "")
                    ].reset_index(drop=True)

                # Key generator for comparison
                def make_comparison_key(row):
                    din_clean = re.sub(r'[^a-zA-Z0-9]', '', row['Notice DIN']).upper()
                    if din_clean and din_clean not in ["", "NAN", "NULL"]:
                        return f"DIN_{din_clean}"
                    proc = re.sub(r'[^a-zA-Z0-9]', '', row['Proceeding Name']).upper()
                    ay = re.sub(r'[^a-zA-Z0-9]', '', row['AY']).upper()
                    sent = re.sub(r'[^a-zA-Z0-9]', '', row['Notice Sent Date']).upper()
                    sect = re.sub(r'[^a-zA-Z0-9]', '', row['Notice Section']).upper()
                    return f"FALLBACK_{proc}_{ay}_{sent}_{sect}"

                df_new_mapped['_comp_key'] = df_new_mapped.apply(make_comparison_key, axis=1)
                if not df_old_mapped.empty:
                    df_old_mapped['_comp_key'] = df_old_mapped.apply(make_comparison_key, axis=1)
                    old_rows = {row['_comp_key']: row for _, row in df_old_mapped.iterrows()}
                else:
                    old_rows = {}

                flagged_rows = []
                for _, new_row in df_new_mapped.iterrows():
                    key = new_row['_comp_key']
                    if key in ["DIN_", "FALLBACK____"]:
                        continue

                    if key not in old_rows:
                        row_dict = new_row.to_dict()
                        row_dict['Flag Reason'] = "NEW NOTICE"
                        flagged_rows.append(row_dict)
                    else:
                        old_row = old_rows[key]
                        updates = []
                        fields_to_check = [
                            ('Proceeding Status', 'Status'),
                            ('Proceeding concluded date', 'Concluded Date'),
                            ('Date of Compliance', 'Compliance Date'),
                            ('Date Response submitted(Last Response Submitted)', 'Response Date')
                        ]
                        for col_name, label in fields_to_check:
                            new_val = str(new_row[col_name]).strip()
                            old_val = str(old_row[col_name]).strip()
                            if new_val.lower() in ["", "nan", "null"]: new_val = ""
                            if old_val.lower() in ["", "nan", "null"]: old_val = ""
                            if new_val != old_val:
                                updates.append(f"{label} ('{old_val}' -> '{new_val}')")
                        
                        if updates:
                            row_dict = new_row.to_dict()
                            row_dict['Flag Reason'] = "UPDATED: " + ", ".join(updates)
                            flagged_rows.append(row_dict)

                if flagged_rows:
                    df_flagged = pd.DataFrame(flagged_rows)
                    # Clean Notice DIN for final output
                    df_flagged['Notice DIN'] = df_flagged['Notice DIN'].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', str(x)).upper() if str(x) not in ["", "nan", "null", "None"] else "")
                    
                    df_flagged = df_flagged[
                        (df_flagged['Notice DIN'] != "") | 
                        (df_flagged['Proceeding Name'] != "")
                    ]
                    
                    if not df_flagged.empty:
                        all_new_notices.append(df_flagged)

            except Exception as e:
                print(f"⚠️ Error parsing layout for {fid} ({pan}): {e}")
                continue
            finally:
                # --- THE BULLETPROOF ARCHIVING ENGINE ---
                try:
                    archive_dir = os.path.join(BASE_DIR, "Archive")
                    if not os.path.exists(archive_dir): 
                        os.makedirs(archive_dir) 
                    
                    # Search the folder for ALL files tied to this PAN and ID type
                    search_pattern = os.path.join(BASE_DIR, f"*_{pan}_{fid}_*.csv")
                    all_files = glob.glob(search_pattern)
                    all_files.sort(key=os.path.getmtime, reverse=True)
                    
                    # Keep the absolute newest file (index 0) in the root. 
                    # Sweep EVERYTHING else into the Archive folder to prevent clutter buildup.
                    if len(all_files) > 1:
                        for f in all_files[1:]:
                            if os.path.exists(f):
                                dest_path = os.path.join(archive_dir, os.path.basename(f))
                                # Prevent Windows [WinError 183] FileExistsError by deleting existing duplicates
                                if os.path.exists(dest_path):
                                    os.remove(dest_path) 
                                shutil.move(f, dest_path)
                                
                except Exception as archive_err:
                    print(f"⚠️ Archiving Engine Error for {fid}: {archive_err}")

    # --- EXPORT REPORT ---
    if all_new_notices:
        final_report = pd.concat(all_new_notices, ignore_index=True)
        
        master_order = [
            'Proceeding Name', 'PAN', 'AY', 'TY', 'Proceeding Limitation Date', 
            'Proceeding Status', 'Proceeding concluded date', 'Notice DIN', 
            'Notice Sent Date', 'Notice Section', 'Date of Compliance', 
            'Date Response submitted(Last Response Submitted)', 'Flag Reason'
        ]
        final_report = final_report.reindex(columns=master_order)
        
        writer = pd.ExcelWriter(OUTPUT_REPORT, engine='xlsxwriter')
        final_report.to_excel(writer, sheet_name='New_Notices', index=False)
        
        workbook  = writer.book
        worksheet = writer.sheets['New_Notices']
        
        header_format = workbook.add_format({
            'bold': True, 'fg_color': '#203764', 'font_color': 'white', 'border': 1, 'text_wrap': True, 'valign': 'vcenter'
        })
        
        for col_num, value in enumerate(final_report.columns.values):
            worksheet.write(0, col_num, value, header_format)
            if value in ['PAN', 'AY', 'TY']: 
                worksheet.set_column(col_num, col_num, 12)
            elif value in ['Proceeding Name', 'Notice DIN', 'Flag Reason']: 
                worksheet.set_column(col_num, col_num, 30)
            else: 
                worksheet.set_column(col_num, col_num, 18)
            
        worksheet.freeze_panes(1, 0)
        writer.close()
        
        print(f"\n✅ [SUCCESS] - Master Report Created & Formatted: {OUTPUT_REPORT}")
    else:
        print("\n✅ [SUCCESS] - Comparison Complete. NO NEW NOTICES FOUND.")


# --- ENTRY POINT ---

if __name__ == "__main__":
    vault_mgr = None
    try:
        # 1. Initialize secure logging vault
        vault_mgr = SecureVaultManager(BASE_DIR)
        
        # Configure logging
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        for h in logger.handlers[:]:
            logger.removeHandler(h)
            
        zip_handler = ZipFileLogHandler(vault_mgr)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        zip_handler.setFormatter(formatter)
        logger.addHandler(zip_handler)
        
        logging.info("Starting CLI execution.")
        logging.info(f"Credentials file: {CREDENTIALS_FILE}")
        logging.info(f"Base directory: {BASE_DIR}")
        
        # 2. Input Validation
        print("ℹ️ [INFO]  - Validating credentials file schema...")
        is_valid, err_layout = validate_credentials_file(CREDENTIALS_FILE)
        if not is_valid:
            print(err_layout)
            logging.error(f"Credentials validation failed:\n{err_layout}")
            sys.exit(1)
        print("✅ [SUCCESS] - Credentials file schema validated successfully!")
        
        # 3. Browser Check/Installation
        if not check_or_install_browser():
            print("🚨 [CRITICAL ERROR] - Playwright browser check/install failed. Exiting.")
            logging.error("Playwright browser check/install failed.")
            sys.exit(1)
            
        # 4. Main Automation Flow
        successful_pans = run_multi_client_downloads(vault_mgr)
        process_and_flag(successful_pans)
        
    except Exception as exc:
        err_type = type(exc).__name__
        err_details = str(exc)
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
        logging.exception("Process structural failure in CLI execution")
        sys.exit(1)