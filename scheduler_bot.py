# scheduler_bot.py
import os
import json
import time
import requests
import asyncio
import websockets
from threading import Thread
import discord

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

CONFIG_DIR   = os.path.join(os.environ["LOCALAPPDATA"], "TAMUClassSwap")
CONFIG_PATH  = os.path.join(CONFIG_DIR, "config.json")
SOCKET_URL   = "wss://api.collegescheduler.com/socket.io/?EIO=3&transport=websocket"
INTERVAL     = 1

CRNS_TO_WATCH: list[str] = []
SWAP_PAIRS: list[dict]   = [] 

COOKIE        = ""
USERNAME      = ""
PASSWORD      = ""
TERM          = ""
TERM_ID       = ""
TYPE          = ""

token         = ""
DISCORD_TOKEN = ""
CHANNEL_NAME  = ""
ACC_ID        = ""
DC_PING_NAME  = ""

notifier      = None
driver        = None
MONITOR_ACTIVE = True

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file missing: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)

def fetch_all_sections(session: requests.Session) -> list[dict]:
    """Return all sections for TERM_ID via Howdy API."""
    url = "https://howdy.tamu.edu/api/course-sections"
    payload = {
        "startRow":     0,
        "endRow":       0,
        "termCode":     TERM_ID,
        "publicSearch": "Y",
    }
    resp = session.post(url, json=payload, headers={"Cookie": COOKIE}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("courseSections", [])


def monitor_crns():
    """Simple watch loop: print and notify status of CRNS_TO_WATCH."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    watch_crns = [str(c) for c in CRNS_TO_WATCH]
    print(f"Starting WATCH mode: checking CRNs {watch_crns} every {INTERVAL}s\n")

    while MONITOR_ACTIVE:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            records = fetch_all_sections(session)
        except Exception as e:
            print(f"[{now}] ERROR fetching sections: {e}")
            time.sleep(INTERVAL)
            continue

        print(f"[{now}] DEBUG: fetched {len(records)} sections")

        status_map: dict[str, dict] = {}
        for r in records:
            crn_val = r.get("SWV_CLASS_SEARCH_CRN")
            crn     = str(crn_val) if crn_val is not None else None
            if not crn:
                continue
            is_open = (r.get("STUSEAT_OPEN") == "Y")
            title   = f"{r.get('SWV_CLASS_SEARCH_SUBJECT')} {r.get('SWV_CLASS_SEARCH_COURSE')} – {r.get('SWV_CLASS_SEARCH_TITLE')}"
            status_map[crn] = {"open": is_open, "title": title}

        for crn in watch_crns:
            info = status_map.get(crn)
            if not info:
                print(f"[{now}] CRN {crn}: ❓ not found")
                continue

            status = "🔓 OPEN" if info["open"] else "🔒 Full"
            print(f"[{now}] CRN {crn} ({info['title']}): {status}")
            if info["open"]:
                notify_discord(f"[{now}] CRN {crn} ({info['title']}): {status}")

        time.sleep(INTERVAL)

def refresh_cookie() -> str:
    """Refresh CollegeScheduler/Howdy cookies via Selenium + SSO."""
    global driver, COOKIE
    print("Refreshing cookie via Selenium…")

    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("user-agent=Mozilla/5.0")

    if not driver:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts,
        )

    wait = WebDriverWait(driver, 30)

    def ensure_ms_login():
        """If on Microsoft login, perform NetID login + Duo flow."""
        try:
            current = driver.current_url
        except Exception:
            return

        if "login.microsoftonline.com" not in current:
            return

        print("[refresh_cookie] On Microsoft login page, attempting SSO login…")

        # Username
        try:
            email_input = wait.until(EC.presence_of_element_located((By.NAME, "loginfmt")))
            email_input.clear()
            email_input.send_keys(USERNAME)
            email_input.send_keys(Keys.RETURN)
            time.sleep(3)
        except Exception as e:
            print("[refresh_cookie] username step skipped:", e)

        # Password
        try:
            password_input = wait.until(EC.presence_of_element_located((By.NAME, "passwd")))
            password_input.clear()
            password_input.send_keys(PASSWORD)
            password_input.send_keys(Keys.RETURN)
            time.sleep(3)
        except Exception as e:
            print("[refresh_cookie] password step skipped:", e)

        # Verification Continue button
        try:
            cont_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "idSIButton9"))
            )
            label = (cont_btn.get_attribute("value") or cont_btn.text or "").strip().lower()
            if "continue" in label:
                print("[refresh_cookie] Clicking Verification 'Continue' button…")
                driver.execute_script("arguments[0].click();", cont_btn)
                time.sleep(3)
        except Exception as e:
            print("[refresh_cookie] verification 'Continue' not found:", e)

        # Duo "trust browser" (if present)
        try:
            yes_device_button = wait.until(
                EC.element_to_be_clickable((By.ID, "trust-browser-button"))
            )
            driver.execute_script("arguments[0].click();", yes_device_button)
            print("[refresh_cookie] Clicked trust-browser-button")
        except Exception:
            print("[refresh_cookie] trust-browser-button not found (likely Duo push flow).")

        # "Stay signed in?" prompt (idSIButton9 with Yes)
        try:
            stay_signed_in = wait.until(
                EC.element_to_be_clickable((By.ID, "idSIButton9"))
            )
            stay_signed_in.click()
            print("[refresh_cookie] Clicked Stay Signed In button")
        except Exception as e:
            print("[refresh_cookie] Stay signed in prompt not encountered:", e)

        # Wait until we are off microsoftonline.com
        try:
            wait.until(lambda d: "microsoftonline.com" not in d.current_url)
            print("[refresh_cookie] SSO complete, redirected to:", driver.current_url)
        except Exception as e:
            print("[refresh_cookie] Did not redirect away from Microsoft login:", e)

    def collect_cookies_for(url: str, sleep_seconds: int = 5, do_login: bool = False) -> dict:
        """Navigate to url, optionally perform login, return dict[name]=value."""
        print(f"[refresh_cookie] Navigating to {url}")
        driver.get(url)
        time.sleep(3)

        if do_login:
            ensure_ms_login()

        time.sleep(sleep_seconds)
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        print(f"[refresh_cookie] Cookies for {url}: {list(cookies.keys())}")
        return cookies

    howdy_cookies = collect_cookies_for("https://howdy.tamu.edu", do_login=True)
    cs_cookies    = collect_cookies_for("https://tamu.collegescheduler.com/entry", do_login=True)

    all_cookies = {**howdy_cookies, **cs_cookies}

    for needed in ["__RequestVerificationToken", ".AspNet.Cookies"]:
        if needed not in all_cookies:
            print(f"[refresh_cookie] WARNING: '{needed}' not found in merged cookies")

    cookie_str = "; ".join(f"{name}={value}" for name, value in all_cookies.items())

    cfg = load_config()
    cfg["cookie"] = cookie_str
    save_config(cfg)

    COOKIE = cookie_str
    print("Cookie refreshed!")
    return cookie_str

def get_token():
    """Get CollegeScheduler API token using the COOKIE."""
    global token
    try:
        resp = requests.get(
            "https://tamu.collegescheduler.com/api/oauth/student/client-credentials/token",
            headers={"Cookie": COOKIE},
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json()["accessToken"]
    except Exception:
        new_ck = refresh_cookie()
        resp = requests.get(
            "https://tamu.collegescheduler.com/api/oauth/student/client-credentials/token",
            headers={"Cookie": new_ck},
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json()["accessToken"]


async def wait_for_reg_response(ws, target_crns: set[str], timeout: float = 10.0):
    """
    Read from the websocket until we see a registration-response
    whose regNumberResponses mention any CRN in target_crns.
    """
    end_time = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < end_time:
        remaining = end_time - asyncio.get_event_loop().time()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return None

        if not isinstance(raw, str) or not raw.startswith("42"):
            continue

        payload = raw[2:]
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if not isinstance(event, list) or len(event) < 2:
            continue

        event_name, data = event[0], event[1]
        if event_name != "registration-response":
            continue

        reg_responses = data.get("regNumberResponses", [])
        if not reg_responses:
            continue

        resp_crns = {str(item.get("regNumber")) for item in reg_responses}
        if target_crns.isdisjoint(resp_crns):
            continue

        return data

    return None


async def send_message():
    global MONITOR_ACTIVE
    MONITOR_ACTIVE = True

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    attempted_pairs: set[tuple[str, str]] = set()
    print(f"[Swap] Watch+Swap mode starting with {len(SWAP_PAIRS)} pair(s).")

    while MONITOR_ACTIVE and SWAP_PAIRS:
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            records = fetch_all_sections(session)
        except Exception as e:
            print(f"[{now}] ERROR fetching sections (Howdy): {e}")
            await asyncio.sleep(INTERVAL)
            continue

        print(f"[{now}] DEBUG: fetched {len(records)} sections")

        status_map: dict[str, dict] = {}
        for r in records:
            crn_val = r.get("SWV_CLASS_SEARCH_CRN")
            crn     = str(crn_val) if crn_val is not None else None
            if not crn:
                continue
            is_open = (r.get("STUSEAT_OPEN") == "Y")
            title   = f"{r.get('SWV_CLASS_SEARCH_SUBJECT')} {r.get('SWV_CLASS_SEARCH_COURSE')} – {r.get('SWV_CLASS_SEARCH_TITLE')}"
            status_map[crn] = {"open": is_open, "title": title}

        open_targets: set[str] = set()
        for pair in SWAP_PAIRS:
            swap_to = str(pair.get("swap_to", "")).strip()
            if not swap_to:
                continue
            info = status_map.get(swap_to)
            if not info:
                continue

            status = "🔓 OPEN" if info["open"] else "🔒 Full"
            print(f"[{now}] SWAP TARGET {swap_to} ({info['title']}): {status}")
            if info["open"]:
                open_targets.add(swap_to)

        if not open_targets:
            print(f"[{now}] No swap_to CRNs open yet; waiting {INTERVAL}s…")
            await asyncio.sleep(INTERVAL)
            continue

        for crn in open_targets:
            info = status_map.get(crn)
            if info:
                msg = f"[{now}] Target CRN {crn} ({info['title']}): 🔓 OPEN – attempting swap…"
                print(msg)
                notify_discord(msg)

        try:
            async with websockets.connect(SOCKET_URL) as ws:
                get_token()
                print("[Swap] Connected to CollegeScheduler WS.")
                print(f"[Swap] Monitoring {len(SWAP_PAIRS)} swap pair(s)...")

                await ws.send(f'420["authorize",{{"token":"{token}"}}]')
                print("[Swap] Sent authorize event")

                for idx, pair in enumerate(list(SWAP_PAIRS)):
                    swap_from = str(pair.get("swap_from", "")).strip()
                    swap_to   = str(pair.get("swap_to", "")).strip()
                    key       = (swap_from, swap_to)

                    if not swap_from or not swap_to:
                        print(f"[Swap] Pair {idx+1}: Invalid - missing CRN(s)")
                        continue

                    if key in attempted_pairs:
                        continue

                    if swap_to not in open_targets:
                        continue

                    print(f"[Swap] Attempting pair {idx+1}: {swap_from} → {swap_to}")
                    target_crns = {swap_from, swap_to}

                    try:
                        payload = (
                            f'421["registration-request",{{'
                            f'"subdomain":"tamu","type":"ENROLL_CART","userId":0,'
                            f'"termCode":"{TERM_ID}",'
                            f'"regNumberRequests":['
                            f'{{"regNumber":"{swap_from}","action":"DW"}},'
                            f'{{"regNumber":"{swap_to}"}}'
                            f'],'
                            f'"additionalData":{{"altPin":""}},'
                            f'"conditionalAddDrop":"Y"'
                            f'}}]'
                        )
                        await ws.send(payload)
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"[Swap] Connection closed while sending registration-request: {e}")
                        break

                    attempted_pairs.add(key)

                    data = await wait_for_reg_response(ws, target_crns, timeout=15)
                    if data is None:
                        print(f"[Swap] Pair {idx+1}: No registration-response in time")
                        continue

                    errors = data.get("errors", [])
                    if errors:
                        print(f"[Swap] Pair {idx+1}: top-level errors: {errors}")

                    reg_responses = data.get("regNumberResponses", [])
                    if not reg_responses:
                        print(f"[Swap] Pair {idx+1}: regNumberResponses empty → Not successful")
                        continue

                    relevant = [
                        r for r in reg_responses
                        if str(r.get("regNumber")) in target_crns
                    ]
                    if not relevant:
                        print(f"[Swap] Pair {idx+1}: response did not include our CRNs → skipping")
                        continue

                    all_success = all(r.get("success", False) for r in relevant)

                    if all_success:
                        msg = f"🎉 SWAP SUCCESSFUL for pair {idx+1}! ({swap_from} → {swap_to})"
                        print(msg)
                        notify_discord(msg)

                        SWAP_PAIRS.pop(idx)
                        cfg = load_config()
                        cfg["swap_pairs"] = SWAP_PAIRS
                        save_config(cfg)
                    else:
                        print(f"[Swap] Pair {idx+1}: Response received but NOT successful")
                        for r in relevant:
                            rn   = r.get("regNumber")
                            sts  = r.get("status")
                            msgs = [m.get("message") for m in r.get("sectionMessages", [])]
                            print(f"    CRN {rn}: status={sts}, messages={msgs}")

                if not SWAP_PAIRS:
                    print("✅ All swap pairs completed successfully!")
                    MONITOR_ACTIVE = False

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[Swap] WS connection closed: {e}. Will resume watch loop…")

        if MONITOR_ACTIVE and SWAP_PAIRS:
            print(f"[Swap] Returning to watch loop; next Howdy poll in {INTERVAL}s…")
            await asyncio.sleep(INTERVAL)

    print("Swap monitor ended.")

def notify_discord(message: str):
    if notifier:
        asyncio.run_coroutine_threadsafe(notifier.send_message(message), notifier.loop)


class DiscordNotifier(discord.Client):
    def __init__(self, channel_name: str):
        super().__init__(intents=discord.Intents.default())
        self.channel_name = channel_name

    async def on_ready(self):
        print(f"Discord bot logged in as {self.user}")

    async def send_message(self, message: str):
        for guild in self.guilds:
            chan = discord.utils.get(guild.text_channels, name=self.channel_name)
            if chan:
                await chan.send(message)
                return

    def start_bot(self, token: str):
        Thread(target=lambda: asyncio.run(self.start(token)), daemon=True).start()

def start_monitoring():
    """Load config and start either watch or swap loop."""
    global notifier, SWAP_PAIRS, COOKIE, USERNAME, PASSWORD
    global TERM, TERM_ID, TYPE, CRNS_TO_WATCH
    global DISCORD_TOKEN, CHANNEL_NAME, ACC_ID, DC_PING_NAME

    cfg = load_config()

    TYPE           = cfg.get("type", "watch")
    DISCORD_TOKEN  = cfg.get("discord_token", "")
    CHANNEL_NAME   = cfg.get("channel_name", "")
    ACC_ID         = cfg.get("discord_account_id", "")

    SWAP_PAIRS     = cfg.get("swap_pairs", [])
    CRNS_TO_WATCH  = cfg.get("crns_to_watch", [])

    COOKIE         = cfg.get("cookie", "")
    USERNAME       = cfg.get("username", "")
    PASSWORD       = cfg.get("password", "")
    TERM           = cfg.get("term_name", "")

    try:
        resp = requests.get(
            "https://howdy.tamu.edu/api/all-terms",
            headers={"Cookie": COOKIE},
            timeout=10,
        )
        resp.raise_for_status()
        all_terms = resp.json()
        term_map = {
            t["STVTERM_DESC"]: t["STVTERM_CODE"]
            for t in all_terms
            if "STVTERM_DESC" in t and "STVTERM_CODE" in t
        }
        global TERM_ID
        TERM_ID = term_map.get(TERM, "")
        if not TERM_ID:
            print(f"[start_monitoring] Warning: could not find term code for '{TERM}'")
        else:
            print(f"[start_monitoring] Using term code {TERM_ID} for '{TERM}'")
    except Exception as e:
        TERM_ID = ""
        print(f"[start_monitoring] Error fetching term list: {e}")

    notifier_local = DiscordNotifier(CHANNEL_NAME)
    if DISCORD_TOKEN:
        notifier_local.start_bot(DISCORD_TOKEN)

    if ACC_ID:
        DC_PING_NAME = f"<@{ACC_ID}>"

    global notifier
    notifier = notifier_local

    if TYPE == "watch":
        monitor_crns()
    elif TYPE == "swap":
        if not SWAP_PAIRS:
            print("No swap pairs configured!")
        else:
            print(f"Starting swap mode with {len(SWAP_PAIRS)} pair(s)")
            asyncio.run(send_message())
    else:
        print("Invalid type in config; must be 'watch' or 'swap'.")


def stop_monitoring():
    global MONITOR_ACTIVE
    MONITOR_ACTIVE = False
    print("Monitoring stopped by user.")
