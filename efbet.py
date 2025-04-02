import asyncio
import json
from datetime import datetime
from pyppeteer import launch
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LiveEfbetMonitor:
    def __init__(self, url="https://www.efbet.com/UK/inplay#action=inplay",
                 output_file="D:/autochrome/gdata/efbet_odds.json", interval=10):
        self.url = url
        self.output_file = output_file
        self.interval = interval
        self.browser = None
        self.page = None
        self.frame = None

    async def initialize_browser(self):
        """Launch browser and open Efbet in-play page."""
        self.browser = await launch(
            headless=True,
            executablePath=r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--start-maximized'],
            defaultViewport=None
        )
        self.page = await self.browser.newPage()
        await self.page.setViewport({"width": 1920, "height": 1080})
        await self.page.setUserAgent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        await self.page.goto(self.url, {'waitUntil': 'networkidle2', 'timeout': 60000})
        logger.info("✅ Browser initialized and Efbet in-play page loaded.")

        # Look for iframe containing in-play data
        iframe_selector = '#inplayAppMain'
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                await self.page.waitForSelector(iframe_selector, {'timeout': 10000})
                iframe_element = await self.page.querySelector(iframe_selector)
                self.frame = await iframe_element.contentFrame()
                if self.frame:
                    logger.info("Switched to iframe: inplayAppMain")
                    await self.frame.waitForSelector('.sportEvents', {'timeout': 10000})
                    logger.info("Found sportEvents inside iframe")
                    # Scroll to load all events
                    await self.frame.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(2)  # Wait for potential lazy-loaded content
                    break
                else:
                    logger.warning(f"Attempt {attempt + 1}/{max_attempts}: Iframe found but contentFrame returned None.")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_attempts}: Error accessing iframe - {str(e)}")
            if attempt == max_attempts - 1:
                logger.info("Falling back to main page carousel data.")
                await self.page.waitForSelector('#SideCarouselMarketGroupListComponent26-carousel-items', {'timeout': 10000})
                logger.info("Found carousel items on main page as fallback.")
                self.frame = None
            await asyncio.sleep(2)

    def parse_betting_data(self, html_content):
        """Parse betting data from the HTML content (iframe or main page)."""
        if not html_content:
            logger.error("⚠️ No HTML content to parse.")
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        betting_data = []

        # Try parsing from sportEvents (iframe content)
        sport_events = soup.find('div', class_='sportEvents')
        if sport_events:
            event_containers = sport_events.find_all('div', class_='eventTbl', recursive=True)
            logger.info(f"Found {len(event_containers)} eventTbl containers.")
            for container in event_containers:
                if 'loading' in container.get('class', []):
                    continue
                title_elem = container.find('div', class_='evntTitle')
                if not title_elem:
                    continue
                teams = title_elem.get_text(strip=True).replace(' In Play', '').strip()
                if any(keyword in teams for keyword in ["Home", "Sport", "Casino", "Login", "loading events"]):
                    continue
                event_id = title_elem.get('data-idfoevent', 'N/A')
                start_time = title_elem.get('data-tsstart', 'N/A')
                event_data = {
                    'teams': teams,
                    'event_id': event_id,
                    'start_time': start_time,
                    'time': 'N/A',
                    'score': 'N/A',
                    'markets': [],
                    'timestamp': datetime.now().isoformat()
                }
                time_elem = container.find('div', class_='min')
                if time_elem:
                    event_data['time'] = time_elem.get_text(strip=True)
                score_elem = container.find('div', class_='result')
                if score_elem:
                    score = score_elem.find('span', class_='ng-binding')
                    if score:
                        event_data['score'] = score.get_text(strip=True)
                markets_container = container.find('div', class_='eventMarkets')
                if markets_container:
                    market_elems = markets_container.find_all('div', class_='marketTbl')
                    for market_elem in market_elems:
                        market_name_elem = market_elem.find('div', class_='marketName')
                        if not market_name_elem:
                            continue
                        market_name = market_name_elem.get_text(strip=True)
                        selections = []
                        selection_elems = market_elem.find_all('div', class_='selection')
                        for sel_elem in selection_elems:
                            if 'inactive' in sel_elem.get('class', []):
                                continue  # Skip inactive selections only
                            outcome_elem = sel_elem.find('div', class_='selectionName')
                            odds_elem = sel_elem.find('span', class_='priceUpDown')
                            if outcome_elem and odds_elem:
                                outcome = outcome_elem.get_text(strip=True)
                                odds = odds_elem.get_text(strip=True)
                                selections.append({'outcome': outcome, 'odds': odds})
                        if selections:
                            event_data['markets'].append({
                                'market': market_name,
                                'selections': selections
                            })
                betting_data.append(event_data)
            logger.info(f"✅ Parsed {len(betting_data)} in-play events from sportEvents.")
            return betting_data

        # Fallback: Parse from carousel items (main page)
        carousel_items = soup.find('div', id='SideCarouselMarketGroupListComponent26-carousel-items')
        if carousel_items:
            carousel_elements = carousel_items.find_all('div', class_='carousel-item')  # Parse all items, not just first
            logger.info(f"Found {len(carousel_elements)} carousel items.")
            for item in carousel_elements:
                market_group = item.find('p').find('span').get_text(strip=True)
                event_data = {
                    'market_group': market_group,
                    'markets': [],
                    'timestamp': datetime.now().isoformat()
                }
                markets = item.find_all('div', class_='carousel-market')
                for market in markets:
                    market_name = market.find('p').find('span').get_text(strip=True)
                    selections = []
                    selection_elems = market.find_all('div', class_='carousel-selection')
                    for sel_elem in selection_elems:
                        outcome = sel_elem.find('span', recursive=False).get_text(strip=True)
                        odds_elem = sel_elem.find('span', class_='price')
                        if odds_elem:
                            odds = odds_elem.get_text(strip=True)
                            selections.append({'outcome': outcome, 'odds': odds})
                    if selections:
                        event_data['markets'].append({
                            'market': market_name,
                            'selections': selections
                        })
                betting_data.append(event_data)
            logger.info(f"✅ Parsed {len(betting_data)} events from carousel items.")
            return betting_data

        logger.warning("⚠️ No sportEvents or carousel items found in the HTML.")
        return []

    def save_to_json(self, data):
        """Save parsed data to JSON file."""
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"✅ Data saved to {self.output_file}")
        except Exception as e:
            logger.error(f"⚠️ Error saving file: {e}")

    async def extract_betting_data(self):
        """Extract betting data from the target context (iframe or main page)."""
        try:
            target = self.frame if self.frame else self.page
            html_content = await target.content()
            odds_data = self.parse_betting_data(html_content)
            return odds_data
        except Exception as e:
            logger.error(f"⚠️ Data extraction error: {e}")
            return []

    async def gather_bets(self):
        """Continuously monitor live bets."""
        await self.initialize_browser()
        try:
            while True:
                odds_data = await self.extract_betting_data()
                self.save_to_json(odds_data)
                logger.info(f"⏳ Waiting {self.interval} seconds for next update...")
                await asyncio.sleep(self.interval)
        except Exception as e:
            logger.error(f"❌ Critical error: {e}")
        finally:
            if self.browser:
                await self.browser.close()
            logger.info("🛑 Browser closed.")

if __name__ == "__main__":
    monitor = LiveEfbetMonitor()
    try:
        asyncio.run(monitor.gather_bets())
    except KeyboardInterrupt:
        logger.info("\n🛑 Monitoring stopped by user")