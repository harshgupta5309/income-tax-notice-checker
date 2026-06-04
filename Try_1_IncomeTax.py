import os
import glob
import shutil
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import re

# --- CONFIGURATION ---
BASE_DIR = r"C:\Users\harsh\OneDrive\Desktop\Income Tax Notice Check er\Income tax folder"
OUTPUT_REPORT = os.path.join(BASE_DIR, "New_Notices_Flagged_Report.xlsx")

# NEW: Path to your Excel file containing the login details
# Excel must have columns exactly named: Login_ID | Password | Name
CREDENTIALS_FILE = r"C:\Users\harsh\OneDrive\Desktop\Income Tax Notice Check er\Credentials.xlsx"

# --- HELPER FUNCTIONS ---

def download_and_rename(page, pan, name, file_id):
    """Handles the CSV download and renaming process"""
    print(f"Triggering download for ID: {file_id}...")
    download_selector = "button.downloadButtonsec"
    
    try:
        with page.expect_download(timeout=60000) as download_info:
            page.locator(download_selector).first.click()
        
        download = download_info.value
        # Added %S (Seconds) to prevent Windows FileExistsError on back-to-back testing
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        # Clean name for Windows
        safe_name = "".join(x for x in name if x.isalnum() or x in " -_").strip()
        
        filename = f"{safe_name}_{pan}_{file_id}_{timestamp}.csv"
        save_path = os.path.join(BASE_DIR, filename)
        
        download.save_as(save_path)
        print(f"✅ Successfully saved: {filename}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to download {file_id}: {e}")
        return False

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

def run_multi_client_downloads():
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)

    try:
        df_creds = pd.read_excel(CREDENTIALS_FILE)
        df_creds.columns = df_creds.columns.str.strip()
        print(f"Loaded {len(df_creds)} clients from credentials file.")
    except Exception as e:
        print(f"CRITICAL ERROR: Could not read credentials file. {e}")
        return []

    processed_pans = []

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True, args=["--start-maximized"])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        print("\nLaunching Income Tax Portal...")
        page.goto("https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en", wait_until="networkidle")

        for index, row in df_creds.iterrows():
            user_id = str(row['Login_ID']).strip()
            password = str(row['Password']).strip()
            
            print(f"\n==================================================")
            print(f"🏢 STARTING CLIENT: {user_id}")
            print(f"==================================================")

            print(f"Scanning for login screen for {user_id}...")
            
            portal_ready = False
            max_checks = 20 
            checks = 0
            
            while not portal_ready and checks < max_checks:
                try:
                    page.wait_for_selector("#panAdhaarUserId", state="visible", timeout=3000)
                    portal_ready = True
                    print("✅ Portal loaded! Injecting credentials...")
                except:
                    checks += 1
                    print(f"⏳ Portal still lagging... searching again. (Check {checks}/{max_checks})")
            
            if not portal_ready:
                print(f"🚨 Portal seems completely down or stuck. Skipping {user_id}.")
                continue 
            
            page.fill("#panAdhaarUserId", user_id)
            page.locator('button.large-button-primary:has-text("Continue")').first.click()
            
            try:
                page.wait_for_selector("#passwordCheckBox-input", timeout=10000)
                page.check("#passwordCheckBox-input", force=True)
                page.fill("#loginPasswordField", password)
                page.keyboard.press("Tab")
            except:
                print(f"Failed to load password screen for {user_id}. Skipping client.")
                continue

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
                
                login_btn = page.locator('button.marTop26')
                if login_btn.is_visible(timeout=2000):
                    login_btn.click(force=True)
                    page.wait_for_timeout(4000)

            if not login_success:
                print(f"ERROR: Login failed for {user_id}. Skipping to next client.")
                continue

            print("Navigating to e-Proceedings...")
            page.wait_for_load_state("networkidle")
            page.locator('[id="Pending Actions"]').wait_for(state="visible", timeout=15000)
            page.locator('[id="Pending Actions"]').click(force=True)
            
            try:
                page.locator('role=menuitem[name="e-Proceedings"]').wait_for(state="visible", timeout=5000)
                page.locator('role=menuitem[name="e-Proceedings"]').click()
            except:
                page.get_by_text("e-Proceedings", exact=True).click()
                
            page.wait_for_load_state("networkidle")

            try:
                page.wait_for_selector(f"text={user_id}", timeout=10000)
                raw_name = page.locator(".mdc-button__label").filter(has_text="Welcome").first.inner_text()
                taxpayer_name = raw_name.replace("Welcome", "").strip()
            except:
                taxpayer_name = str(row['Name']).strip() if pd.notna(row['Name']) else "Taxpayer"

            download_and_rename(page, user_id, taxpayer_name, "AX")
            
            page.get_by_text("For your Information", exact=False).click()
            page.wait_for_timeout(2000)
            download_and_rename(page, user_id, taxpayer_name, "BX")
            
            page.locator('span.mat-button-toggle-label-content:has-text("Of Other PAN/TAN")').click()
            page.wait_for_timeout(3000)
            download_and_rename(page, user_id, taxpayer_name, "AY")
            
            page.get_by_text("For your Information", exact=False).click()
            page.wait_for_timeout(2000)
            download_and_rename(page, user_id, taxpayer_name, "BY")

            processed_pans.append(user_id)

            print(f"Logging out {user_id}...")
            page.locator('button.profileMenubtn').wait_for(state="visible", timeout=5000)
            page.locator('button.profileMenubtn').click()
            page.wait_for_timeout(1000) 
            
            try:
                page.locator('role=menuitem[name="Log Out"]').click()
            except:
                page.get_by_text("Log Out", exact=True).click()
            
            page.wait_for_load_state("networkidle")

            try:
                login_again_btn = page.locator('button.registerButton:has-text("Log In Again")')
                login_again_btn.wait_for(state="visible", timeout=5000)
                login_again_btn.click()
                page.wait_for_load_state("networkidle")
            except:
                print("Could not find 'Log In Again' button. Hard navigating back to login page...")
                page.goto("https://eportal.incometax.gov.in/iec/foservices/#/login?language-code=en", wait_until="networkidle")

        print("\nAll clients processed. Closing browser...")
        browser.close()
        
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
        print("No valid PANs processed. Skipping comparison.")
        return

    print("\n==================================================")
    print("📊 STARTING STRICT TEMPLATE MAPPING (HIGH-ASSURANCE)")
    print("==================================================")

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
                        print(f"ℹ️ File {fid} for {pan} has no active rows (No Records Found). Skipping.")
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
        
        print(f"\n🚀 Master Report Created & Formatted: {OUTPUT_REPORT}")
    else:
        print("\n✅ Comparison Complete. NO NEW NOTICES FOUND.")


# --- ENTRY POINT ---

if __name__ == "__main__":
    successful_pans = run_multi_client_downloads()
    process_and_flag(successful_pans)