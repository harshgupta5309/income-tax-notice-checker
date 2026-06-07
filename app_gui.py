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
    LOG_HTML_PATH = os.path.join(sys._MEIPASS, "security_log.html")
else:
    # Running in a standard local python interpreter
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    HTML_PATH = os.path.join(APP_DIR, "code.html")
    LOG_HTML_PATH = os.path.join(APP_DIR, "security_log.html")

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
        self._decision_event = threading.Event()
        self.user_decision = None
        self._log_window = None
        self.log_history = []
        self.abort_requested = False
        
        # Load saved settings immediately on initialization to sync Python backend state
        try:
            settings_path = os.path.join(APP_DIR, "settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                if "credentials_path" in settings and settings["credentials_path"]:
                    tax_backend.CREDENTIALS_FILE = settings["credentials_path"]
                if "destination_path" in settings and settings["destination_path"]:
                    tax_backend.BASE_DIR = settings["destination_path"]
        except Exception:
            pass

    def set_window(self, window):
        self._window = window

    def prompt_user_server_delay(self, pan, selector):
        """Called by the background thread to display the delay prompt in the UI and await decision."""
        self._decision_event = threading.Event()
        self.user_decision = None
        
        # Fire evaluation on UI to show the dialog/prompt below client name
        js_cmd = f"showServerDelayPrompt('{pan}', '{selector}')"
        self._window.evaluate_js(js_cmd)
        
        # Block until self._decision_event is set
        self._decision_event.wait()
        
        # Return the choice: 'wait', 'skip', or 'stop'
        return self.user_decision

    def submit_user_decision(self, decision):
        """Called by the UI thread to resolve the blocked wait in the background thread."""
        self.user_decision = decision
        self._decision_event.set()
        return True

    def toggle_fullscreen(self):
        """Toggles fullscreen state of the native webview window"""
        if self._window:
            self._window.toggle_fullscreen()
            return True
        return False

    def abort_pipeline(self):
        """Sets the global abort flag to stop the backend automation run immediately"""
        self.abort_requested = True
        tax_backend.ABORT_SIGNAL = True
        print("🛑 Abort request received. Signaling backend pipeline to terminate...")
        return True

    def get_log_history(self):
        """Returns the accumulated log history as a JSON string for the log window"""
        return json.dumps(self.log_history)

    def download_credentials_template(self):
        """Launches a topmost native file save dialog to download the template credentials spreadsheet"""
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.asksaveasfilename(
                title="Save Credentials Template",
                defaultextension=".xlsx",
                filetypes=[("Excel Files", "*.xlsx"), ("CSV Files", "*.csv")],
                initialfile="Credentials_Template.xlsx"
            )
            root.destroy()
            if file_path:
                import pandas as pd
                df = pd.DataFrame(columns=["Login_ID", "Password", "Name"])
                # Add a sample row to guide the user
                df.loc[0] = ["PAN1234567", "Password123", "Sample Taxpayer Name"]
                
                if file_path.endswith('.csv'):
                    df.to_csv(file_path, index=False)
                else:
                    df.to_excel(file_path, index=False)
                return json.dumps({"success": True, "path": file_path})
            return json.dumps({"success": False, "error": "Cancelled by user"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def open_destination_folder(self):
        """Opens the destination folder in Windows Explorer"""
        base_dir = tax_backend.BASE_DIR
        if os.path.exists(base_dir):
            try:
                if sys.platform == "win32":
                    os.startfile(base_dir)
                    return json.dumps({"success": True})
                else:
                    import subprocess
                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.call([opener, base_dir])
                    return json.dumps({"success": True})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": False, "error": "Folder not found"})

    def open_security_log_window(self):
        """Opens a new native window to display the Security Log stream."""
        if self._log_window:
            return True
            
        # Write default security_log.html template if it doesn't exist
        if not os.path.exists(LOG_HTML_PATH):
            default_log_html = """<!DOCTYPE html>
<html>
<head>
    <title>Litigation OS | Security Log</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;700&display=swap" rel="stylesheet">
    <style>
        body {
            background-color: #0A0A0A;
            color: rgba(255, 255, 255, 0.9);
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            padding: 20px;
            margin: 0;
            overflow-y: auto;
            line-height: 1.6;
        }
        .log-entry {
            border-left: 2px solid rgba(255,255,255,0.1);
            padding-left: 10px;
            margin-bottom: 6px;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .log-info { border-color: rgba(255,255,255,0.2); }
        .log-success { border-color: #34D399; color: #34D399; }
        .log-warning { border-color: #E05A47; color: #E05A47; }
        .log-error { border-color: #EF4444; color: #EF4444; font-weight: bold; }
        .title-bar {
            font-family: 'Inter', sans-serif;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: rgba(255, 255, 255, 0.4);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding-bottom: 8px;
            margin-bottom: 15px;
        }
    </style>
</head>
<body>
    <div class="title-bar">System Diagnostic Stream &bull; Live Ledger</div>
    <div id="log-container"></div>
    <script>
        function printToLogWindow(msg) {
            const container = document.getElementById('log-container');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            
            // Highlight styles based on prefix
            if (msg.includes('✅') || msg.includes('SUCCESS')) {
                entry.className += ' log-success';
            } else if (msg.includes('⚠️') || msg.includes('WARNING')) {
                entry.className += ' log-warning';
            } else if (msg.includes('🚨') || msg.includes('CRITICAL') || msg.includes('ERROR')) {
                entry.className += ' log-error';
            } else {
                entry.className += ' log-info';
            }
            
            entry.innerText = msg;
            container.appendChild(entry);
            window.scrollTo(0, document.body.scrollHeight);
        }

        window.addEventListener('pywebviewready', async function() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.get_log_history) {
                const logsJson = await window.pywebview.api.get_log_history();
                const logs = JSON.parse(logsJson);
                logs.forEach(msg => printToLogWindow(msg));
            }
        });
    </script>
</body>
</html>
"""
            try:
                with open(LOG_HTML_PATH, "w", encoding="utf-8") as f:
                    f.write(default_log_html)
            except Exception:
                pass
                
        self._log_window = webview.create_window(
            title="Litigation OS | Security Log Ledger",
            url=LOG_HTML_PATH,
            width=700,
            height=500,
            js_api=self,
            background_color='#0A0A0A'
        )
        self._log_window.events.closed += self._on_log_window_closed
        return True

    def _on_log_window_closed(self):
        self._log_window = None

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

    # --- DIRECTORY PERSISTENCE SETTINGS HELPERS ---
    def _save_settings(self, credentials_path=None, destination_path=None):
        """Saves credentials_path and destination_path to settings.json inside APP_DIR"""
        settings_path = os.path.join(APP_DIR, "settings.json")
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            except Exception:
                pass
        if credentials_path is not None:
            settings["credentials_path"] = credentials_path
        if destination_path is not None:
            settings["destination_path"] = destination_path
        try:
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def load_saved_settings(self):
        """Exposed API to load saved paths from settings.json"""
        settings_path = os.path.join(APP_DIR, "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                # Apply paths to backend when loading settings
                if "credentials_path" in settings and settings["credentials_path"]:
                    tax_backend.CREDENTIALS_FILE = settings["credentials_path"]
                if "destination_path" in settings and settings["destination_path"]:
                    tax_backend.BASE_DIR = settings["destination_path"]
                return json.dumps(settings)
            except Exception:
                pass
        return json.dumps({"credentials_path": "", "destination_path": ""})

    def save_theme_preference(self, theme_name):
        """Saves the UI theme preference ('obsidian' or 'charcoal') to settings.json"""
        self._save_settings()  # ensure file exists
        settings_path = os.path.join(APP_DIR, "settings.json")
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            except Exception:
                pass
        settings["theme"] = theme_name
        try:
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=4)
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
            if file_path:
                self._save_settings(credentials_path=file_path)
                tax_backend.CREDENTIALS_FILE = file_path
                return file_path
            return ""
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
            if folder_path:
                self._save_settings(destination_path=folder_path)
                tax_backend.BASE_DIR = folder_path
                return folder_path
            return ""
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
        redirector = JSLogRedirector(self._window, self)
        try:
            # Safely hook print output streams to update the browser ledger interface
            sys.stdout = redirector
            
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
            
            # Reset the abort signal before starting the pipeline
            tax_backend.ABORT_SIGNAL = False
            self.abort_requested = False
            self.log_history = []
            
            # Start backend scraper routine
            successful_pans = tax_backend.run_multi_client_downloads(api_ref=self)
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
            # Write the complete execution log to the vault at the end of the run to prevent file lock contention
            if redirector.log_buffer:
                log_content = "\n".join(redirector.log_buffer) + "\n"
                self.write_to_secure_vault("run_execution.log", log_content.encode('utf-8'))

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

    def get_client_download_history(self, pan):
        """Searches BASE_DIR and BASE_DIR/Archive for downloaded CSV files for this PAN"""
        import glob
        from datetime import datetime
        base_dir = tax_backend.BASE_DIR
        if not base_dir or not os.path.exists(base_dir):
            return json.dumps([])

        pan_upper = pan.upper().strip()

        # Gather files from BASE_DIR and BASE_DIR/Archive
        files = []
        # Pattern 1: in base_dir
        pattern_base = os.path.join(base_dir, f"*_{pan_upper}_*.csv")
        files.extend(glob.glob(pattern_base))

        # Pattern 2: in Archive folder
        archive_dir = os.path.join(base_dir, "Archive")
        if os.path.exists(archive_dir):
            pattern_archive = os.path.join(archive_dir, f"*_{pan_upper}_*.csv")
            files.extend(glob.glob(pattern_archive))

        # Also search lowercase 'archive' just in case
        archive_dir_lower = os.path.join(base_dir, "archive")
        if os.path.exists(archive_dir_lower) and archive_dir_lower != archive_dir:
            pattern_archive_lower = os.path.join(archive_dir_lower, f"*_{pan_upper}_*.csv")
            files.extend(glob.glob(pattern_archive_lower))

        seen_paths = set()
        records = []
        for f in files:
            abs_path = os.path.abspath(f)
            if abs_path in seen_paths:
                continue
            seen_paths.add(abs_path)

            filename = os.path.basename(abs_path)
            # Try to identify file_id (AX, BX, AY, BY) from filename
            file_id = "Unknown"
            for fid in ["AX", "BX", "AY", "BY"]:
                if f"_{fid}_" in filename:
                    file_id = fid
                    break
            
            # Get mtime as fallback
            mtime = os.path.getmtime(abs_path)
            dt = datetime.fromtimestamp(mtime)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

            # Try to parse timestamp from filename robustly (supports space, dash, or underscore separators)
            import re
            ts_match = re.search(r'(\d{4})[ -_](\d{2})[ -_](\d{2})[ -_](\d{2})[ -_](\d{2})(?:[ -_](\d{2}))?', filename)
            if ts_match:
                year = ts_match.group(1)
                month = ts_match.group(2)
                day = ts_match.group(3)
                hour = ts_match.group(4)
                minute = ts_match.group(5)
                second = ts_match.group(6) if ts_match.group(6) else "00"
                formatted_time = f"{year}-{month}-{day} {hour}:{minute}:{second}"

            records.append({
                "filename": filename,
                "filepath": abs_path,
                "file_id": file_id,
                "timestamp": formatted_time,
                "raw_time": mtime
            })

        # Sort by raw_time descending (newest first)
        records.sort(key=lambda x: x["raw_time"], reverse=True)
        return json.dumps(records)

    def open_downloaded_file(self, filepath):
        """Opens the specified CSV file with the default system application"""
        import sys
        if os.path.exists(filepath):
            try:
                if sys.platform == "win32":
                    os.startfile(filepath)
                    return json.dumps({"success": True})
                else:
                    import subprocess
                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.call([opener, filepath])
                    return json.dumps({"success": True})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": False, "error": "File not found."})

class JSLogRedirector:
    """Interceptors to catch raw console print messages and stream them directly to the HTML UI"""
    def __init__(self, window, api_ref):
        self.window = window
        self.api_ref = api_ref
        self.log_buffer = []

    def write(self, string):
        if string.strip():
            # Escape strings carefully to safeguard the V8 string parser from crashes
            clean_str = string.replace("\r", "").replace("\n", " ").strip()
            clean_str = clean_str.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            
            # Safely append console string inside JS
            self.window.evaluate_js(f"printToConsole('{clean_str}', 'info')")
            
            # Append to history in api_ref
            self.api_ref.log_history.append(clean_str)
            
            # Streaming to the child log window if it exists
            if self.api_ref._log_window:
                try:
                    self.api_ref._log_window.evaluate_js(f"printToLogWindow('{clean_str}')")
                except Exception:
                    pass
            
            # Accumulate logs in memory buffer to prevent locks on diagnostics zip file
            log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_buffer.append(f"[{log_time}] {string.strip()}")

            # Parse terminal indicators to drive UI milestones
            if "Loaded" in string and "clients" in string:
                match = re.search(r'Loaded (\d+) clients', string)
                if match:
                    self.window.evaluate_js(f"updateLoadedClientsCount({match.group(1)})")

            elif "🏢 STARTING CLIENT:" in string:
                client_pan = string.split("🏢 STARTING CLIENT:")[-1].strip()
                self.window.evaluate_js(f"onClientCycleStarted('{client_pan}')")

            elif "🔑 [STAGE-AUTH] -" in string:
                match = re.search(r'🔑 \[STAGE-AUTH\] -\s*(\d+)%\s*-\s*(.*)', string)
                if match:
                    pct = int(match.group(1))
                    msg = match.group(2).strip()
                    self.window.evaluate_js(f"updateAuthProgressBar({pct}, '{msg}')")

            elif "📥 [STAGE-EXTRACTION] -" in string:
                match = re.search(r'📥 \[STAGE-EXTRACTION\] -\s*(\d+)%\s*-\s*(.*)', string)
                if match:
                    pct = int(match.group(1))
                    msg = match.group(2).strip()
                    self.window.evaluate_js(f"updateExtractionProgressBar({pct}, '{msg}')")

            elif "👤 CLIENT_INFO:" in string:
                parts = string.split("👤 CLIENT_INFO:")[-1].strip().split(" | ")
                if len(parts) == 2:
                    pan, name = parts[0].strip(), parts[1].strip()
                    self.window.evaluate_js(f"onClientLoggedIn('{pan}', '{name}')")

            elif "Triggering download for ID:" in string:
                file_id = string.split("Triggering download for ID:")[-1].strip().rstrip('.')
                self.window.evaluate_js(f"onExtractionStarted('{file_id}')")

            elif "Successfully saved:" in string:
                file_info = string.split("Successfully saved:")[-1].strip()
                pool_match = re.search(r'_(AX|BX|AY|BY)_', file_info)
                pool_type = pool_match.group(1) if pool_match else "Notice Pool"
                self.window.evaluate_js(f"onFileDownloaded('{pool_type}', '{file_info}', true)")
                self.window.evaluate_js(f"onFileStatusUpdated('{pool_type}', 'Downloaded', 'success')")

            elif "has no active rows" in string or "No Records Found" in string:
                match = re.search(r'File\s+(AX|BX|AY|BY)', string)
                pool_type = match.group(1) if match else "Notice Pool"
                self.window.evaluate_js(f"onFileDownloaded('{pool_type}', 'No records found on server.', false)")
                self.window.evaluate_js(f"onFileStatusUpdated('{pool_type}', 'No Records', 'warning')")

            elif "download stage failed for" in string:
                match = re.search(r'(AX|BX|AY|BY) download stage failed for', string)
                pool_type = match.group(1) if match else "Notice Pool"
                self.window.evaluate_js(f"onFileStatusUpdated('{pool_type}', 'Failed', 'error')")

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
