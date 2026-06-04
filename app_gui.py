import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog
import webview
import re
import logging
import Try_1_IncomeTax as tax_backend

# 1. Resolve dynamic path boundaries for bundled assets inside PyInstaller
if getattr(sys, 'frozen', False):
    # Running as a compiled PyInstaller executable
    APP_DIR = os.path.dirname(sys.executable)
    HTML_PATH = os.path.join(sys._MEIPASS, "tax-litigation-suite.html")
else:
    # Running as a raw Python script
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    HTML_PATH = os.path.join(APP_DIR, "tax-litigation-suite.html")

# Define global variable overrides to sync output paths with back-end script
tax_backend.BASE_DIR = os.path.join(APP_DIR, "Income_tax_folder")

class DesktopAPI:
    """
    Exposed API structure for the pywebview JS bridge.
    All public methods defined here can be called asynchronously in JS via:
    window.pywebview.api.methodName(args)
    """
    def __init__(self):
        self._window = None
        self.running_thread = None
        self._thread_lock = threading.Lock()

    def set_window(self, window):
        self._window = window

    # --- NATIVE OS FILE/FOLDER BROWSERS ---
    def browse_credentials(self):
        """
        Opens a native Windows file picker to locate the Credentials Excel file.
        This runs in an isolated Tkinter context configured to sit topmost.
        """
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="Select Credentials Sheet",
                filetypes=[("Excel Files", "*.xlsx")]
            )
            root.destroy()
            return file_path if file_path else ""
        except Exception as e:
            return f"Error: {str(e)}"

    def browse_destination(self):
        """
        Opens a native Windows folder browser to configure the target outputs path.
        """
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder_path = filedialog.askdirectory(title="Select Destination Folder")
            root.destroy()
            return folder_path if folder_path else ""
        except Exception as e:
            return f"Error: {str(e)}"

    # --- NATIVE FILE LAUNCHERS ---
    def open_excel_report(self):
        """
        Instructs the host operating system to immediately launch the generated
        notice reconciliation report directly inside Microsoft Excel.
        """
        report_path = os.path.join(tax_backend.BASE_DIR, "New_Notices_Flagged_Report.xlsx")
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
        return {"success": False, "error": f"Report not found at: {report_path}"}

    # --- AUTOMATION THREADING INTERFACE ---
    def start_notice_check(self, credentials_path, destination_path):
        """
        Spins up the Playwright automation sequence on a background daemon worker thread.
        This ensures the web-based UI remains interactive and fully animated.
        """
        with self._thread_lock:
            if self.running_thread and self.running_thread.is_alive():
                return {"success": False, "error": "Automation engine is already running!"}

            # Pre-flight Path and Structure Validations
            if not os.path.exists(credentials_path):
                return {"success": False, "error": "Selected Credentials registry file does not exist!"}

            # Update paths dynamically in the automation backend module based on UI inputs
            tax_backend.CREDENTIALS_FILE = credentials_path
            tax_backend.BASE_DIR = destination_path
            tax_backend.OUTPUT_REPORT = os.path.join(destination_path, "New_Notices_Flagged_Report.xlsx")

            if not os.path.exists(destination_path):
                os.makedirs(destination_path, exist_ok=True)

            # Spin up Thread
            self.running_thread = threading.Thread(target=self._run_automation_task, daemon=True)
            self.running_thread.start()
            return {"success": True}

    def _run_automation_task(self):
        """Execution task wrapper that captures output logs during runtime"""
        try:
            # Set up print stream interceptor to pipe terminal messages straight to HTML logs
            sys.stdout = JSLogRedirector(self._window)
            
            # Initialize secure logging vault from backend
            vault_mgr = tax_backend.SecureVaultManager(tax_backend.BASE_DIR)
            
            # Configure logging
            logger = logging.getLogger()
            logger.setLevel(logging.DEBUG)
            for h in logger.handlers[:]:
                logger.removeHandler(h)
            zip_handler = tax_backend.ZipFileLogHandler(vault_mgr)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            zip_handler.setFormatter(formatter)
            logger.addHandler(zip_handler)
            
            # Execute backend automation tasks
            successful_pans = tax_backend.run_multi_client_downloads(vault_mgr)
            tax_backend.process_and_flag(successful_pans)
            
            # Fire successful complete hook in JS context
            self._window.evaluate_js("onNativeAutomationComplete()")
        except Exception as e:
            self._window.evaluate_js(f"onNativeAutomationError('{str(e)}')")
        finally:
            # Revert system stream handler back to console default on thread termination
            sys.stdout = sys.__stdout__

class JSLogRedirector:
    """
    Stream helper that intercepts sys.stdout writes and schedules them
    safely on the webview window GUI thread as JavaScript function executions.
    """
    def __init__(self, window):
        self.window = window

    def write(self, string):
        if string.strip():
            # Clean and escape the string values to prevent broken JavaScript calls
            clean_str = string.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", " ").strip()
            self.window.evaluate_js(f"printToConsole('{clean_str}', 'info')")
            
            # Dynamic regex and string parsers to translate stdout prints into live GUI actions
            if "Loaded" in string and "clients" in string:
                match = re.search(r'Loaded (\d+) clients', string)
                if match:
                    count = match.group(1)
                    self.window.evaluate_js(f"updateLoadedClientsCount({count})")

            elif "🏢 STARTING CLIENT:" in string:
                client_id = string.split("🏢 STARTING CLIENT:")[-1].strip()
                self.window.evaluate_js(f"onClientCycleStarted('{client_id}')")
                
            elif "Scanning for login screen" in string:
                self.window.evaluate_js("updateAuthStatus(25, 'Locating Login Form...')")

            elif "✅ Portal loaded! Injecting credentials..." in string:
                self.window.evaluate_js("updateAuthStatus(55, 'Submitting Credentials...')")

            elif "Navigating to e-Proceedings..." in string:
                self.window.evaluate_js("updateAuthStatus(85, 'Opening e-Proceedings Section...')")

            elif "Triggering download for ID:" in string:
                file_id = string.split("Triggering download for ID:")[-1].strip()
                self.window.evaluate_js(f"onExtractionStarted('{file_id}')")

            elif "✅ Successfully saved:" in string:
                file_info = string.split("Successfully saved:")[-1].strip()
                # Parse filename details to identify Pool Type and Filename
                pool_match = re.search(r'_(AX|BX|AY|BY)_', file_info)
                pool_type = pool_match.group(1) if pool_match else "Notice Pool"
                self.window.evaluate_js(f"onFileDownloaded('{pool_type}', '{file_info}', true)")
                
            elif "ℹ️ File" in string and "has no active rows" in string:
                match = re.search(r'File (AX|BX|AY|BY) for', string)
                pool_type = match.group(1) if match else "Notice Pool"
                self.window.evaluate_js(f"onFileDownloaded('{pool_type}', 'No active records detected.', false)")

    def flush(self):
        pass

def main():
    api = DesktopAPI()
    # Create webview instance matching our visual styling
    window = webview.create_window(
        title="Income Tax Litigation Suite",
        url=HTML_PATH,
        js_api=api,
        width=1280,
        height=850,
        min_size=(1024, 768),
        background_color='#0E0E0E'
    )
    api.set_window(window)
    # Launch browser window (disable debug in production to hide context developer tools)
    webview.start(debug=False)

if __name__ == "__main__":
    main()
