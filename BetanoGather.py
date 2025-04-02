import asyncio
import re
import json
import logging
from pyppeteer import launch
from bs4 import BeautifulSoup
from datetime import datetime


class BetanoScraper:
    """Robust scraper combining working extraction with original output structure"""

    def __init__(self, output_file="betano_data.json",
                 executable_path=r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 headless=True):
        self.executable_path = executable_path
        self.headless = headless
        self.url = 'https://www.betano.bg/en/live/'
        self.output_file = output_file
        self.previous_data = []
        self.REFRESH_INTERVAL = 10
        logging.basicConfig(level=logging.INFO)

    @staticmethod
    def safe_text(element, default="N/A"):
        """Safe text extraction with HTML entity decoding"""
        if not element:
            return default
        return element.get_text(strip=True).replace('\xa0', ' ') if element else default

    @staticmethod
    def extract_time_minutes(time_str):
        """Robust time parser with validation"""
        try:
            clean_str = re.sub(r'[^\d:]', '', time_str)
            parts = clean_str.split(':')
            if len(parts) >= 2:
                return int(parts[0])
            return int(clean_str) if clean_str else None
        except Exception:
            return None

    async def setup_browser(self):
        """Browser setup with anti-bot measures"""
        return await launch(
            headless=self.headless,
            executablePath=self.executable_path,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--window-size=1920x1080'
            ]
        )

    async def extract_match_data(self, match):
        """Extract data from single match card with original format"""
        try:
            # Time extraction
            time_element = match.select_one('[data-qa="live-event-time"] span')
            time_str = self.safe_text(time_element, "00:00")
            minutes = self.extract_time_minutes(time_str)

            if minutes is None or minutes > 120:
                return None

            # Teams extraction
            team_elements = match.select('[data-qa="participants"] div.tw-truncate')
            if len(team_elements) < 2:
                return None
            teams = [self.safe_text(t) for t in team_elements[:2]]

            # Score extraction
            score_elements = match.select('[data-qa="score"] span.tw-text-white-snow')
            score = f"{self.safe_text(score_elements[0])}-{self.safe_text(score_elements[1])}" if len(
                score_elements) >= 2 else 'N/A-N/A'

            # Odds extraction (maintain list format)
            odds = []
            market_container = match.select_one('div.tw-flex.tw-flex-row.tw-flex-1.tw-items-center.tw-justify-center')
            if market_container:
                for btn in market_container.select('[data-qa="event-selection"]'):
                    price_span = btn.select_one('span.tw-text-sem-color-text-highlight')
                    odds.append(self.safe_text(price_span, "N/A"))
            odds = odds[:3] + ["N/A"] * (3 - len(odds))  # Ensure 3 odds

            return {
                'minutes': minutes,
                'time_str': time_str,
                'teams': teams,
                'score': score,
                'odds': odds,  # Original list format
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            logging.error(f"Match processing error: {str(e)}")
            return None

    async def get_live_matches(self, page):
        """Main data extraction flow"""
        await page.waitForSelector('[data-qa="event-card"]', timeout=30000)
        await asyncio.sleep(3)  # Allow dynamic loading

        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        matches = soup.select('[data-qa="event-card"]')

        valid_matches = []
        for match in matches:
            match_data = await self.extract_match_data(match)
            if match_data:
                valid_matches.append(match_data)

        return sorted(valid_matches, key=lambda x: x['minutes'], reverse=True)

    def print_data(self, matches):
        """Original print format"""
        print(
            f"\n🏆 Live Matches ({len(matches)} found) - Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'═' * 50}")
        for match in matches:
            print(f"\n⚽ {match['teams'][0]} vs {match['teams'][1]}")
            print(f"⏱️ {match['time_str']} | 📊 {match['score']}")
            print(f"{'─' * 50}")
            if any(odd != "N/A" for odd in match['odds']):
                print(f"│ 1 │ {match['odds'][0]:<6} │ X │ {match['odds'][1]:<6} │ 2 │ {match['odds'][2]:<6} │")
            else:
                print("│ Odds not available │")
            print(f"╰──────────────────────────────────────╯")

    def save_to_file(self, matches):
        """Original saving logic"""
        if matches != self.previous_data:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(matches, f, ensure_ascii=False, indent=4)
            self.previous_data = matches.copy()
            logging.info(f"Data saved to {self.output_file}")

    async def monitor_page(self):
        """Enhanced monitoring loop"""
        browser = None
        try:
            browser = await self.setup_browser()
            page = await browser.newPage()
            await page.setUserAgent(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            await page.setViewport({'width': 1920, 'height': 1080})

            # Initial navigation
            await page.goto(self.url, {'waitUntil': 'networkidle2', 'timeout': 60000})

            # Cookie consent
            try:
                await page.click('button#CybotCookiebotDialogBodyButtonAccept', timeout=3000)
                await asyncio.sleep(1)
            except Exception:
                pass

            logging.info("Starting monitoring...")
            while True:
                try:
                    matches = await self.get_live_matches(page)
                    self.print_data(matches)
                    self.save_to_file(matches)
                    await asyncio.sleep(self.REFRESH_INTERVAL)
                except Exception as e:
                    logging.error(f"Monitoring error: {str(e)}")
                    await asyncio.sleep(self.REFRESH_INTERVAL * 2)

        except Exception as e:
            logging.error(f"Fatal error: {str(e)}")
        finally:
            if browser:
                await browser.close()


if __name__ == "__main__":
    scraper = BetanoScraper(output_file="D:/autochrome/gdata/betano_data.json")
    try:
        asyncio.get_event_loop().run_until_complete(scraper.monitor_page())
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user")