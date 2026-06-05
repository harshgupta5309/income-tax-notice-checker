import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog
import webview
import json
import re
import ctypes
import platform
import pyzipper
from datetime import datetime
import Try_1_IncomeTax as tax_backend

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

# Sync initial path references with the back-end automation scraper
tax_backend.BASE_DIR = BASE_DIR
tax_backend.OUTPUT_REPORT = os.path.join(BASE_DIR, "New_Notices_Flagged_Report.xlsx")

class DesktopAPI:
    """
    Exposed Python API methods callable asynchronously from the HTML frontend.
    These are made available inside JavaScript under window.pywebview.api.*
    """
    def __init__(self):
        self._window = None
        self.running_thread = None
        self._thread_lock = threading.Lock()
        self.vault_folder = None

    def set_window(self, window):
        self._window = window

    # --- PORTABLE DIAGNOSTICS VAULT ENGINE ---
    def _initialize_vault(self, destination_path):
        """Creates an ultra-hidden system folder to securely store log backups"""
        self.vault_folder = os.path.join(destination_path, ".diagnostics_vault")
        if not os.path.exists(self.vault_folder):
            os.makedirs(self.vault_folder, exist_ok=True)
        
        # Apply Windows kernel hidden attributes so it is invisible to a standard explorer window
        if platform.system() == "Windows":
            # 0x02 = HIDDEN, 0x04 = SYSTEM (Super-hidden file attribute)
            try:
                ctypes.windll.kernel32.SetFileAttributesW(self.vault_folder, 0x06)
            except Exception:
                pass

    def write_to_secure_vault(self, filename, content_bytes):
        """Commits diagnostic dumps or snapshots into a password-locked zip archive"""
        if not self.vault_folder:
            return
        
        zip_path = os.path.join(self.vault_folder, "diagnostics.zip")
        # Use pyzipper (pure-Python AES-256) to prevent any PyInstaller compile-time DLL conflicts
        try:
            with pyzipper.AESZipFile(zip_path, 'a', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.SEC_EX_AES_256) as zf:
                zf.setpassword(b"Harsh@123")
                zf.writestr(filename, content_bytes)
        except Exception:
            pass

    # --- NATIVE FILE/FOLDER PICKERS ---
    def browse_credentials(self):
        """Launches a topmost native file picker to select the client spreadsheet"""
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="Select Credentials Registry File",
                filetypes=[("Excel Files", "*.xlsx")]
            )
            root.destroy()
            return file_path if file_path else ""
        except Exception as e:
            return f"Error: {str(e)}"

    def browse_destination(self):
        """Launches a topmost native folder browser to set the output directory"""
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder_path = filedialog.askdirectory(title="Configure Target Output Folder")
            root.destroy()
            return folder_path if folder_path else ""
        except Exception as e:
            return f"Error: {str(e)}"

    # --- RECONCILIATION FILE LAUNCHERS ---
    def open_excel_report(self):
        """Instructs the host operating system to cleanly open the generated spreadsheet report"""
        report_path = tax_backend.OUTPUT_REPORT
        if os.path.exists(report_path):
            try:
                if sys.platform == "win32":
                    os.startfile(report_path)
                    return {"success": True}
                else:
                    import subprocess
                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.call([opener, report_path])
                    return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": f"Notice reconciliation spreadsheet not found."}

    def get_clients_from_registry(self, credentials_path):
        """Reads the Excel spreadsheet and returns a list of clients (Name and PAN)"""
        if not os.path.exists(credentials_path):
            return json.dumps([])
        try:
            import pandas as pd
            df = pd.read_excel(credentials_path)
            df.columns = df.columns.str.strip()
            clients = []
            for _, row in df.iterrows():
                login_id = str(row.get('Login_ID', '')).strip()
                name = str(row.get('Name', '')).strip()
                if login_id:
                    clients.append({
                        "name": name if name else "Taxpayer",
                        "pan": login_id
                    })
            return json.dumps(clients)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def check_default_credentials(self):
        """Checks if Credentials.xlsx exists in the app folder and returns its path and client list"""
        default_path = tax_backend.CREDENTIALS_FILE
        if os.path.exists(default_path):
            try:
                import pandas as pd
                df = pd.read_excel(default_path)
                df.columns = df.columns.str.strip()
                clients = []
                for _, row in df.iterrows():
                    login_id = str(row.get('Login_ID', '')).strip()
                    name = str(row.get('Name', '')).strip()
                    if login_id:
                        clients.append({
                            "name": name if name else "Taxpayer",
                            "pan": login_id
                        })
                return json.dumps({"path": default_path, "clients": clients})
            except Exception:
                pass
        return json.dumps({"path": "", "clients": []})

    def get_flagged_pans(self):
        """Reads the final report and returns a list of PANs that have flagged updates"""
        report_path = tax_backend.OUTPUT_REPORT
        if not os.path.exists(report_path):
            return json.dumps([])
        try:
            import pandas as pd
            df = pd.read_excel(report_path)
            if 'PAN' in df.columns:
                pans = df['PAN'].dropna().unique().tolist()
                return json.dumps(pans)
        except Exception:
            pass
        return json.dumps([])

    # --- AUTOMATION WORKER INTERFACE ---
    def start_notice_check(self, credentials_path, destination_path):
        """Spins up the Playwright scrapers inside a decoupled background daemon thread"""
        with self._thread_lock:
            if self.running_thread and self.running_thread.is_alive():
                return {"success": False, "error": "An active extraction thread is already running!"}

            if not os.path.exists(credentials_path):
                return {"success": False, "error": "Credentials registry Excel spreadsheet path is invalid!"}

            # Map paths dynamically to the backend module
            tax_backend.CREDENTIALS_FILE = credentials_path
            tax_backend.BASE_DIR = destination_path
            tax_backend.OUTPUT_REPORT = os.path.join(destination_path, "New_Notices_Flagged_Report.xlsx")

            # Setup the invisible diagnostics log box container
            self._initialize_vault(destination_path)

            self.running_thread = threading.Thread(target=self._run_automation_pipeline, daemon=True)
            self.running_thread.start()
            return {"success": True}

    def _run_automation_pipeline(self):
        try:
            # Safely hook print output streams to update the browser ledger interface
            sys.stdout = JSLogRedirector(self._window, self)
            
            # Configure logging to output to stdout
            import logging
            logger = logging.getLogger()
            logger.setLevel(logging.DEBUG)
            for h in logger.handlers[:]:
                logger.removeHandler(h)
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            logger.addHandler(ch)
            
            # Start backend scraper routine
            successful_pans = tax_backend.run_multi_client_downloads()
            tax_backend.process_and_flag(successful_pans)
            
            # Fire completion actions on UI
            self._window.evaluate_js("onNativeAutomationComplete()")
        except Exception as e:
            # Write error stack traces securely to our hidden, encrypted diagnostics archive
            error_msg = f"Fatal Pipeline Error: {str(e)}"
            self.write_to_secure_vault(f"error_{int(datetime.now().timestamp())}.txt", error_msg.encode('utf-8'))
            self._window.evaluate_js(f"onNativeAutomationError('{str(e)}')")
        finally:
            sys.stdout = sys.__stdout__ # Reset print redirects back to default output

    def get_client_notices(self, pan):
        """Reads local CSV files to feed notice listings dynamically to the slide-out drawers"""
        import glob
        search_pattern = os.path.join(tax_backend.BASE_DIR, f"*_{pan}_AX_*.csv")
        files = glob.glob(search_pattern)
        if not files:
            return json.dumps({"notices": []})

        files.sort(key=os.path.getmtime, reverse=True)
        latest_ax_file = files[0]

        try:
            df = tax_backend.load_portal_csv(latest_ax_file)
            if df.empty:
                return json.dumps({"notices": []})

            notices_list = []
            for _, row in df.iterrows():
                # Extract columns dynamically using robust fallback names
                din = str(row.get('Notice DIN', row.get('Notice ID', 'N/A'))).strip()
                proceeding = str(row.get('Proceeding Name', 'Scrutiny Assessment')).strip()
                section = str(row.get('Notice Section', row.get('Section', 'N/A'))).strip()
                status = str(row.get('Proceeding Status', row.get('Status', 'PENDING'))).strip()

                notices_list.append({
                    "din": din,
                    "proceeding": proceeding,
                    "section": section,
                    "status": status.upper()
                })
            return json.dumps({"notices": notices_list})
        except Exception as e:
            return json.dumps({"error": str(e)})

class JSLogRedirector:
    """Interceptors to catch raw console print messages and stream them directly to the HTML UI"""
    def __init__(self, window, api_ref):
        self.window = window
        self.api_ref = api_ref

    def write(self, string):
        if string.strip():
            # Escape strings carefully to safeguard the V8 string parser from crashes
            clean_str = string.replace("\r", "").replace("\n", " ").strip()
            clean_str = clean_str.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            
            # Safely append console string inside JS
            self.window.evaluate_js(f"printToConsole('{clean_str}', 'info')")
            
            # Back up logs continuously inside our secure, password-locked diagnostics zip
            log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.api_ref.write_to_secure_vault("run_execution.log", f"[{log_time}] {clean_str}\n".encode('utf-8'))

            # Parse terminal indicators to drive UI milestones
            if "Loaded" in string and "clients" in string:
                match = re.search(r'Loaded (\d+) clients', string)
                if match:
                    self.window.evaluate_js(f"updateLoadedClientsCount({match.group(1)})")

            elif "🏢 STARTING CLIENT:" in string:
                client_pan = string.split("🏢 STARTING CLIENT:")[-1].strip()
                self.window.evaluate_js(f"onClientCycleStarted('{client_pan}')")

            elif "Scanning for login screen" in string:
                self.window.evaluate_js("updateAuthProgressBar(30, 'Searching for secure login portal form...')")

            elif "✅ Portal loaded! Injecting credentials..." in string:
                self.window.evaluate_js("updateAuthProgressBar(65, 'Decrypting and injecting password payload...')")

            elif "Navigating to e-Proceedings..." in string:
                self.window.evaluate_js("updateAuthProgressBar(90, 'Opening secure e-Proceedings sector...')")

            elif "Triggering download for ID:" in string:
                file_id = string.split("Triggering download for ID:")[-1].strip()
                self.window.evaluate_js(f"onExtractionStarted('{file_id}')")

            elif "Successfully saved:" in string:
                file_info = string.split("Successfully saved:")[-1].strip()
                pool_match = re.search(r'_(AX|BX|AY|BY)_', file_info)
                pool_type = pool_match.group(1) if pool_match else "Notice Pool"
                self.window.evaluate_js(f"onFileDownloaded('{pool_type}', '{file_info}', true)")

            elif "has no active rows" in string or "No Records Found" in string:
                match = re.search(r'File (AX|BX|AY|BY) for', string)
                pool_type = match.group(1) if match else "Notice Pool"
                self.window.evaluate_js(f"onFileDownloaded('{pool_type}', 'No records found on server.', false)")

    def flush(self):
        pass

def main():
    api = DesktopAPI()
    window = webview.create_window(
        title="Litigation OS | Neo-Classical Portal Engine",
        url=HTML_PATH,
        js_api=api,
        width=1320,
        height=880,
        min_size=(1024, 768),
        background_color='#EFECE6'
    )
    api.set_window(window)
    # Start webview engine
    webview.start(debug=False)

if __name__ == "__main__":
    main()
