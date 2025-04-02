import asyncio, json, os, subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import threading, unicodedata, re
from pyppeteer import connect
from fuzzywuzzy import fuzz
from utils.WinBetGather import LiveWinBetMonitor
from utils.BetanoGather import BetanoScraper
from utils.OrbitGather import OrbitXScraper
from utils.efbet import LiveEfbetMonitor

# === Configuration ===
CHROME_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
REMOTE_DEBUGGING_PORT = 9222
DATA_DIR = r"D:\autochrome\gdata"

SITE_URLS = {
    "WinBet": "https://winbet.bg/in-play?sportId=soccer-1001",
    "Betano": "https://www.betano.bg/en/live/",
    "Efbet": "https://www.efbet.com/UK/inplay#action=inplay"
}

# Global variables
async_loop = None
browser = None
browser_connected = False
chrome_process = None
site_tasks = {}
checkbox_vars = {}
checkbox_widgets = {}
status_label = None
analysis_tree = None
analysis_frame = None

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


def load_orbitx_data():
    orbitx_dict = {}
    try:
        with open(os.path.join(DATA_DIR, "orbitx_latest.json"), "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                match_data = entry.get("match_data", {})
                teams = [match_data.get("team1", ""), match_data.get("team2", "")]
                normalized_key = tuple(sorted([normalize_team_name(t) for t in teams]))

                outcomes = {}
                for oc_data in match_data.get("outcomes", []):
                    oc = oc_data.get("outcome")
                    outcomes[oc] = {
                        "back_odds": oc_data.get("back_odds", "N/A"),
                        "lay_odds": oc_data.get("lay_odds", "N/A")
                    }

                orbitx_dict[normalized_key] = {
                    "outcomes": {
                        "1": outcomes.get("1", {"back_odds": "N/A", "lay_odds": "N/A"}),
                        "X": outcomes.get("X", {"back_odds": "N/A", "lay_odds": "N/A"}),
                        "2": outcomes.get("2", {"back_odds": "N/A", "lay_odds": "N/A"}),
                    },
                    "minutes": match_data.get("minutes", 0),
                    "original_teams": teams
                }
        return orbitx_dict
    except Exception as e:
        print(f"Error loading OrbitX data: {e}")
        return {}


# -----------------------
# Enhanced Team Name Normalization
# -----------------------
def normalize_team_name(name):
    if not name or not isinstance(name, str):
        return ""

    # Normalize unicode and convert to lowercase
    name = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("utf-8").lower().strip()

    # Remove punctuation and special characters
    name = re.sub(r'[^\w\s]', '', name)

    # Remove common suffixes and abbreviations
    suffixes = {'women', 'u21', 'u23', 'reserves', 'ii', 'iii', 'fc', 'cf', 'cd', 'ca', 'team', 'ac', 'afc'}
    words = re.split(r'\s+', name)
    filtered_words = [word for word in words if word not in suffixes]

    # Remove numbers and remaining special characters
    filtered_words = [re.sub(r'\d+', '', word) for word in filtered_words]

    # Rebuild normalized name
    normalized = ' '.join(filtered_words).strip()
    normalized = re.sub(r'\s+', ' ', normalized)

    return normalized


# -----------------------
# Improved Minute Parsing
# -----------------------
def get_minutes(match):
    try:
        time_str = str(match.get("minutes", 0))
        # Handle cases like '45+2' => 47
        if '+' in time_str:
            parts = time_str.split('+')
            base = int(parts[0]) if parts[0] else 0
            added = sum(int(p) for p in parts[1:] if p)
            return base + added
        return int(time_str)
    except:
        return 0


# -----------------------
# Optimized Team Matching
# -----------------------
def match_teams(team1, team2, threshold=85):
    # Use token_set_ratio for better partial matching
    return fuzz.token_set_ratio(team1, team2) >= threshold


# -----------------------
# Advanced Match Merging
# -----------------------
def merge_matches(wb_dict, bt_dict, ef_dict, orbitx_dict):
    all_keys = set(wb_dict.keys()) | set(bt_dict.keys()) | set(ef_dict.keys()) | set(orbitx_dict.keys())

    orbitx_matches = []
    all_three = []
    two_providers = []
    unique = []

    for key in all_keys:
        providers = []
        if key in wb_dict: providers.append('wb')
        if key in bt_dict: providers.append('bt')
        if key in ef_dict: providers.append('ef')
        orbitx_data = orbitx_dict.get(key, None)

        entry = {
            'wb': wb_dict.get(key),
            'bt': bt_dict.get(key),
            'ef': ef_dict.get(key),
            'orbitx': orbitx_data,
            'minutes': max(
                wb_dict.get(key, {}).get('minutes', 0),
                bt_dict.get(key, {}).get('minutes', 0),
                ef_dict.get(key, {}).get('minutes', 0),
                orbitx_data.get('minutes', 0) if orbitx_data else 0
            ),
            'provider_count': len(providers),
            'original_teams': next(
                (m['original_teams'] for m in [wb_dict.get(key), bt_dict.get(key), ef_dict.get(key), orbitx_data] if m),
                []
            )
        }

        # Prioritize OrbitX matches
        if orbitx_data:
            orbitx_matches.append(entry)
        else:
            if len(providers) == 3:
                all_three.append(entry)
            elif len(providers) == 2:
                two_providers.append(entry)
            else:
                unique.append(entry)

    # Sort OrbitX matches by number of supporting providers
    orbitx_matches.sort(key=lambda x: (-x['provider_count'], -x['minutes']))

    # Sort other groups
    all_three.sort(key=lambda x: -x['minutes'])
    two_providers.sort(key=lambda x: -x['minutes'])
    unique.sort(key=lambda x: -x['minutes'])

    return orbitx_matches, all_three, two_providers, unique


def load_site_data(file_path, site_name):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            site_dict = {}

            for match in data:
                processed_match = {
                    "teams": [],
                    "odds": ["N/A", "N/A", "N/A"],
                    "minutes": 0,
                    "score": "N/A",
                    "original_teams": []
                }

                # Common structure for WinBet and Betano
                if site_name in ["WinBet", "Betano"]:
                    processed_match["teams"] = match.get("teams", [])
                    processed_match["odds"] = match.get("odds", ["N/A", "N/A", "N/A"])
                    processed_match["minutes"] = get_minutes(match)
                    processed_match["score"] = match.get("score", "N/A")
                    processed_match["original_teams"] = processed_match["teams"]

                # Efbet-specific processing
                elif site_name == "Efbet":
                    # Extract and split teams
                    teams = match.get("teams", "")
                    if isinstance(teams, str):
                        processed_match["teams"] = [t.strip() for t in teams.split(" - ")]
                    else:
                        processed_match["teams"] = teams

                    # Extract match result odds
                    for market in match.get("markets", []):
                        if market.get("market", "").lower() == "match result":
                            selections = market.get("selections", [])
                            if len(selections) >= 3:
                                processed_match["odds"] = [
                                    selections[0].get("odds", "N/A"),
                                    selections[1].get("odds", "N/A"),
                                    selections[2].get("odds", "N/A")
                                ]

                    # Parse time to minutes
                    time_str = match.get("time", "")
                    if "minute" in time_str.lower():
                        try:
                            processed_match["minutes"] = int(''.join(filter(str.isdigit, time_str)))
                        except:
                            processed_match["minutes"] = 0
                    elif "half" in time_str.lower():
                        processed_match["minutes"] = 45
                    else:
                        processed_match["minutes"] = 0

                    processed_match["score"] = match.get("score", "N/A")
                    processed_match["original_teams"] = processed_match["teams"]

                # Create normalized key if valid teams exist
                if len(processed_match["teams"]) == 2:
                    normalized_key = tuple(sorted([normalize_team_name(t) for t in processed_match["teams"]]))
                    site_dict[normalized_key] = processed_match

            return site_dict
    except Exception as e:
        print(f"Error loading {site_name} data: {e}")
        return {}


# -----------------------
# Data Processing & Analysis View Update
# -----------------------
def load_betting_data():
    return (
        load_site_data(os.path.join(DATA_DIR, "winbet_odds.json"), "WinBet"),
        load_site_data(os.path.join(DATA_DIR, "betano_data.json"), "Betano"),
        load_site_data(os.path.join(DATA_DIR, "efbet_odds.json"), "Efbet"),
        load_orbitx_data()  # Must be 4th return value
    )


def format_orbitx(data):
    if not data or not data.get('outcomes'):
        return "N/A"

    odds_str = []
    for outcome in ['1', 'X', '2']:
        oc_data = data['outcomes'].get(outcome, {})
        back = oc_data.get('back_odds', 'N/A')
        lay = oc_data.get('lay_odds', 'N/A')
        odds_str.append(f"{outcome}: {back}/{lay}")
    return "\n".join(odds_str)


def get_max_back_odds(entry, outcome_index):
    odds_list = []
    for provider in ['wb', 'ef', 'bt']:  # WinBet, Efbet, Betano
        if entry.get(provider):
            odds = entry[provider].get('odds', ["N/A", "N/A", "N/A"])[outcome_index]
            if odds != "N/A":
                try:
                    odds_list.append(float(odds))
                except ValueError:
                    pass
    return max(odds_list) if odds_list else None


# -----------------------
# Updated Analysis View with Arbitrage
# -----------------------
def update_analysis_view():
    wb_dict, bt_dict, ef_dict, orbitx_dict = load_betting_data()
    orbitx_matches, all_three, two_providers, unique = merge_matches(wb_dict, bt_dict, ef_dict, orbitx_dict)

    analysis_tree.delete(*analysis_tree.get_children())

    def format_provider_odds(data):
        """Return only the odds lines for a given provider."""
        if not data:
            return "N/A"
        odds = data.get("odds", ["N/A", "N/A", "N/A"])
        return f"1: {odds[0]}\nX: {odds[1]}\n2: {odds[2]}"

    # Build the Match column string
    def format_match_column(entry):
        teams = entry.get('original_teams', [])
        minutes = entry.get('minutes', 0)
        # Try to get a score from one of the providers; here we pick from WinBet as an example
        score = "N/A"
        if entry.get('wb') and entry['wb'].get('score'):
            score = entry['wb'].get('score')
        elif entry.get('bt') and entry['bt'].get('score'):
            score = entry['bt'].get('score')
        elif entry.get('ef') and entry['ef'].get('score'):
            score = entry['ef'].get('score')
        elif entry.get('orbitx') and entry['orbitx'].get('score'):
            score = entry['orbitx'].get('score')
        return f"{teams[0]} vs {teams[1]} ({minutes}')\nScore: {score}"

    # Insert matches in priority order
    for group in [orbitx_matches, all_three, two_providers, unique]:
        for entry in group:
            teams = entry.get('original_teams', [])
            if not teams or len(teams) != 2:
                continue

            # Get OrbitX lay odds
            orbitx_lay_odds = {}
            if entry.get('orbitx'):
                for oc in ['1', 'X', '2']:
                    lay_odds = entry['orbitx']['outcomes'].get(oc, {}).get('lay_odds', 'N/A')
                    if lay_odds != 'N/A':
                        try:
                            orbitx_lay_odds[oc] = float(lay_odds)
                        except ValueError:
                            orbitx_lay_odds[oc] = 'N/A'
                    else:
                        orbitx_lay_odds[oc] = 'N/A'
            else:
                orbitx_lay_odds = {'1': 'N/A', 'X': 'N/A', '2': 'N/A'}

            # Calculate arbitrage for each outcome
            arbitrage_text = []
            for oc_idx, oc_name in zip([0, 1, 2], ['1', 'X', '2']):
                max_back_odds = get_max_back_odds(entry, oc_idx)
                if max_back_odds is None:
                    continue
                lay_odds = orbitx_lay_odds.get(oc_name, 'N/A')
                if lay_odds == 'N/A':
                    continue
                if max_back_odds > lay_odds:
                    profit = 1000 * (max_back_odds / lay_odds - 1)
                    arbitrage_text.append(f"{oc_name}: ${profit:.2f}")

            arbitrage_str = ", ".join(arbitrage_text) if arbitrage_text else "N/A"

            analysis_tree.insert("", "end", values=(
                format_match_column(entry),
                format_provider_odds(entry.get('wb')),
                format_provider_odds(entry.get('ef')),
                format_provider_odds(entry.get('bt')),
                format_orbitx(entry.get('orbitx')),
                arbitrage_str
            ))

    analysis_frame.after(10000, update_analysis_view)


# -----------------------
# GUI Profile Selection (Unchanged)
# -----------------------
def select_profile_gui():
    user_data_dir = os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data')
    local_state_path = os.path.join(user_data_dir, 'Local State')
    try:
        with open(local_state_path, 'r', encoding='utf-8') as f:
            local_state = json.load(f)
        profiles = local_state.get('profile', {}).get('info_cache', {})
        profile_list = [(info['name'], dir_name) for dir_name, info in profiles.items()]
        if not profile_list:
            messagebox.showerror("Error", "No Chrome profiles found. Exiting...")
            exit(1)
    except Exception as e:
        messagebox.showerror("Error", f"Error reading Chrome profiles: {e}")
        exit(1)

    selected_profile = None

    def confirm_selection():
        nonlocal selected_profile
        selected_index = listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Selection Error", "Please select a profile.")
            return
        index = selected_index[0]
        selected_profile = profile_list[index][1]
        root.destroy()

    root = tk.Tk()
    root.title("Select Chrome Profile")
    root.geometry("350x200")
    tk.Label(root, text="Select a Chrome Profile:").pack(pady=10)
    listbox = tk.Listbox(root, width=40)
    for name, dir_name in profile_list:
        listbox.insert(tk.END, f"{name} ({dir_name})")
    listbox.pack(pady=10)
    confirm_button = tk.Button(root, text="Confirm", command=confirm_selection)
    confirm_button.pack(pady=10)
    root.mainloop()

    if selected_profile is None:
        print("No profile selected. Exiting...")
        exit(1)
    print(f"Selected profile: {selected_profile}")
    return selected_profile


# -----------------------
# Async Monitoring Functions (Unchanged)
# -----------------------
async def monitor_winbet(live_monitor, page):
    url = SITE_URLS["WinBet"]
    await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    while True:
        try:
            matches = await live_monitor.extract_live_matches()
            live_monitor.display_matches(matches)
            live_monitor.save_to_file(matches)
        except Exception as e:
            print(f"Error in WinBet monitoring: {e}")
        await asyncio.sleep(10)


async def monitor_betano(betano_scraper, page):
    await page.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/91.0.4472.124 Safari/537.36'
    )
    await page.setViewport({'width': 1920, 'height': 1080})
    await page.goto(SITE_URLS["Betano"], {'waitUntil': 'networkidle2', 'timeout': 60000})
    try:
        await page.click('button#CybotCookiebotDialogBodyButtonAccept', timeout=5000)
        await asyncio.sleep(3)
    except Exception:
        pass
    while True:
        try:
            matches = await betano_scraper.get_live_matches(page)
            betano_scraper.print_data(matches)
            betano_scraper.save_to_file(matches)
        except Exception as e:
            print(f"Error in Betano monitoring: {e}")
        await asyncio.sleep(10)


async def monitor_efbet(live_efbet_monitor, page):
    live_efbet_monitor.page = page
    live_efbet_monitor.browser = browser

    await page.setViewport({"width": 1920, "height": 1080})
    await page.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    )
    await page.goto(SITE_URLS["Efbet"], {'waitUntil': 'networkidle2', 'timeout': 60000})
    print("✅ Efbet in-play page loaded.")

    iframe_selector = '#inplayAppMain'
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            await page.waitForSelector(iframe_selector, {'timeout': 10000})
            iframe_element = await page.querySelector(iframe_selector)
            live_efbet_monitor.frame = await iframe_element.contentFrame()
            if live_efbet_monitor.frame:
                print("Switched to iframe: inplayAppMain")
                await live_efbet_monitor.frame.waitForSelector('.sportEvents', {'timeout': 10000})
                print("Found sportEvents inside iframe")
                await live_efbet_monitor.frame.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await asyncio.sleep(2)
                break
            else:
                print(f"Attempt {attempt + 1}/{max_attempts}: Iframe found but contentFrame returned None.")
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_attempts}: Error accessing iframe - {str(e)}")
        if attempt == max_attempts - 1:
            print("Falling back to main page carousel data.")
            await page.waitForSelector('#SideCarouselMarketGroupListComponent26-carousel-items', {'timeout': 10000})
            print("Found carousel items on main page as fallback.")
            live_efbet_monitor.frame = None
        await asyncio.sleep(10)

    while True:
        try:
            matches = await live_efbet_monitor.extract_betting_data()
            print("Efbet data:", matches)
            live_efbet_monitor.save_to_json(matches)
        except Exception as e:
            print(f"Error in Efbet monitoring: {e}")
        await asyncio.sleep(live_efbet_monitor.interval)


# -----------------------
# Browser Management (Unchanged)
# -----------------------
async def init_browser():
    global browser, browser_connected
    for _ in range(10):
        try:
            browser = await connect(browserURL=f'http://127.0.0.1:{REMOTE_DEBUGGING_PORT}')
            print("Connected to Chrome.")
            browser_connected = True
            return
        except Exception as e:
            print(f"Connection attempt failed: {e}")
            await asyncio.sleep(1)
    print("Failed to connect to Chrome after multiple attempts.")
    browser_connected = False


def start_async_loop_thread(profile_dir):
    global async_loop, chrome_process
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)
    chrome_args = [
        CHROME_PATH,
        f'--remote-debugging-port={REMOTE_DEBUGGING_PORT}',
        f'--profile-directory={profile_dir}',
        '--window-size=1920,1080',
        '--window-position=0,0',
        '--force-device-scale-factor=1'
    ]
    print("Launching Chrome with remote debugging...")
    chrome_process = subprocess.Popen(chrome_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    async_loop.run_until_complete(init_browser())
    if browser_connected:
        async_loop.run_forever()
    else:
        print("Browser connection failed. Exiting...")
        chrome_process.terminate()
        exit(1)


# -----------------------
# GUI Setup (Modified for Arbitrage)
# -----------------------
def toggle_site(site_name):
    global future
    state = checkbox_vars[site_name].get()
    if state:
        if not browser_connected:
            print("Browser is not ready yet. Please wait a moment.")
            checkbox_vars[site_name].set(False)
            return
        if site_name in site_tasks:
            print(f"{site_name} is already being monitored.")
            return
        # For the other sites, a new page is created from the existing browser
        if site_name in ["WinBet", "Betano", "Efbet"]:
            page_future = asyncio.run_coroutine_threadsafe(browser.newPage(), async_loop)
            page = page_future.result()
            if site_name == "WinBet":
                live_monitor = LiveWinBetMonitor()
                live_monitor.browser = browser
                live_monitor.page = page
                future = asyncio.run_coroutine_threadsafe(monitor_winbet(live_monitor, page), async_loop)
            elif site_name == "Betano":
                betano_scraper = BetanoScraper(output_file=os.path.join(DATA_DIR, "betano_data.json"))
                future = asyncio.run_coroutine_threadsafe(monitor_betano(betano_scraper, page), async_loop)
            elif site_name == "Efbet":
                live_efbet_monitor = LiveEfbetMonitor(
                    url=SITE_URLS["Efbet"],
                    output_file=os.path.join(DATA_DIR, "efbet_odds.json"))
                future = asyncio.run_coroutine_threadsafe(monitor_efbet(live_efbet_monitor, page), async_loop)
            site_tasks[site_name] = (future, page)
            print(f"Started monitoring {site_name}.")
        elif site_name == "OrbitX":
            # Create an instance of OrbitXScraper and pass the shared browser page
            page_future = asyncio.run_coroutine_threadsafe(browser.newPage(), async_loop)
            page = page_future.result()
            orbitx_scraper = OrbitXScraper(executable_path=CHROME_PATH, headless=True)
            future = asyncio.run_coroutine_threadsafe(
                orbitx_scraper._run_continuous(interval=30, verbose=True, page=page), async_loop)
            site_tasks[site_name] = (future, page)
            print("Started monitoring OrbitX.")
    else:
        if site_name in site_tasks:
            future, page = site_tasks.pop(site_name)
            future.cancel()
            if page is not None:
                asyncio.run_coroutine_threadsafe(page.close(), async_loop)
            print(f"Stopped monitoring {site_name}.")
        else:
            print(f"{site_name} was not being monitored.")


def create_gui():
    gui = tk.Tk()
    gui.title("Live Odds Comparator")
    gui.geometry("1200x1100")
    gui.attributes("-topmost", True)

    style = ttk.Style()
    style.configure("Treeview", rowheight=50)

    global status_label, analysis_tree, analysis_frame

    top_frame = tk.Frame(gui)
    top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

    status_label = ttk.Label(top_frame, text="Browser Status: Not Ready")
    status_label.pack(pady=5)
    ttk.Label(top_frame, text="Select Site(s) to Monitor:").pack(pady=5)

    for site in ["WinBet", "Efbet", "Betano", "OrbitX"]:
        var = tk.BooleanVar()
        checkbox_vars[site] = var
        cb = ttk.Checkbutton(top_frame, text=site, variable=var, command=lambda s=site: toggle_site(s))
        cb.pack(side=tk.LEFT, padx=20)
        checkbox_widgets[site] = cb

    analysis_frame = tk.Frame(gui)
    analysis_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=10)

    columns = ("Match", "WinBet", "Efbet", "Betano", "OrbitX", "Arbitrage")
    analysis_tree = ttk.Treeview(analysis_frame, columns=columns, show="headings")
    analysis_tree.heading("Match", text="Match (Time & Score)", anchor='w')
    analysis_tree.heading("WinBet", text="WinBet Odds", anchor='center')
    analysis_tree.heading("Efbet", text="Efbet Odds", anchor='center')
    analysis_tree.heading("Betano", text="Betano Odds", anchor='center')
    analysis_tree.heading("OrbitX", text="OrbitX (Back/Lay)", anchor='center')
    analysis_tree.heading("Arbitrage", text="Arbitrage Opportunities", anchor='center')

    analysis_tree.column("Match", width=300, anchor='w')
    analysis_tree.column("WinBet", width=150, anchor='center')
    analysis_tree.column("Efbet", width=150, anchor='center')
    analysis_tree.column("Betano", width=150, anchor='center')
    analysis_tree.column("OrbitX", width=200, anchor='center')
    analysis_tree.column("Arbitrage", width=200, anchor='center')

    analysis_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    analysis_tree.tag_configure('arbitrage', background='lightgreen')
    scrollbar = ttk.Scrollbar(analysis_frame, orient="vertical", command=analysis_tree.yview)
    analysis_tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def check_browser_status():
        if browser_connected:
            status_label.config(text="Browser Status: Ready")
            for cb in checkbox_widgets.values():
                cb.config(state="normal")
        else:
            status_label.config(text="Browser Status: Not Ready")
            for cb in checkbox_widgets.values():
                cb.config(state="disabled")
        gui.after(500, check_browser_status)

    check_browser_status()
    update_analysis_view()

    def on_closing():
        for site_name, (future, page) in list(site_tasks.items()):
            future.cancel()
            asyncio.run_coroutine_threadsafe(page.close(), async_loop)
        site_tasks.clear()
        if async_loop is not None:
            async_loop.call_soon_threadsafe(async_loop.stop)
        if chrome_process is not None:
            chrome_process.terminate()
            chrome_process.wait()
        gui.destroy()

    gui.protocol("WM_DELETE_WINDOW", on_closing)
    gui.mainloop()


# -----------------------
# Main Program Flow
# -----------------------
if __name__ == "__main__":
    selected_profile_dir = select_profile_gui()
    threading.Thread(target=start_async_loop_thread, args=(selected_profile_dir,), daemon=True).start()
    create_gui()