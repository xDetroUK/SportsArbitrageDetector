import asyncio
import re
import json
import os
from datetime import datetime
from pyppeteer import launch
from bs4 import BeautifulSoup


class OrbitXScraper:
    """
    A scraper class for extracting and continuously saving live match data from the OrbitX exchange website.
    """

    def __init__(self, executable_path=r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", headless=True):
        self.executable_path = executable_path
        self.headless = headless
        self.url = 'https://www.orbitxch.com/customer/sport/1'

    @staticmethod
    def safe_text(element, default="N/A"):
        return element.text.strip() if element else default

    @staticmethod
    def extract_time_minutes(time_str):
        match = re.search(r'(\d+)', time_str)
        return int(match.group(1)) if match else None

    async def scrape_once(self, verbose=True, page=None):
        """
        Performs a single scrape and returns structured data.
        If a page is provided, it will be used (and not closed by this method);
        otherwise, a new browser and page will be created.
        """
        created_browser = False
        browser = None
        data = []
        try:
            if page is None:
                # Launch a new browser only if a page is not provided.
                browser = await launch(
                    headless=self.headless,
                    executablePath=self.executable_path,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--window-size=1920x1080'
                    ],
                    handleSIGINT=False,
                    handleSIGTERM=False,
                    handleSIGHUP=False
                )
                page = await browser.newPage()
                created_browser = True

            await page.setUserAgent(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/91.0.4472.124 Safari/537.36'
            )
            await page.setViewport({'width': 1920, 'height': 1080})

            await page.goto(self.url, {'waitUntil': 'networkidle2', 'timeout': 60000})
            await page.waitForSelector('.biab_group-markets-table-row', {'timeout': 30000})
            await asyncio.sleep(3)  # Wait for final rendering

            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            matches = soup.select('.biab_group-markets-table-row')

            valid_matches = []
            for match in matches:
                time_str = self.safe_text(match.find('span', class_='styles_soccer__time__W39zL'))
                minutes = self.extract_time_minutes(time_str)
                if minutes is not None:
                    valid_matches.append((minutes, match))

            valid_matches.sort(key=lambda x: x[0], reverse=True)

            # Extract structured data
            for minutes, match in valid_matches:
                time_str = self.safe_text(match.find('span', class_='styles_soccer__time__W39zL'))
                scores = match.find_all('span', class_='styles_soccer__score__CWJPr')
                score = f"{self.safe_text(scores[0])}-{self.safe_text(scores[1])}" if len(scores) >= 2 else 'N/A-N/A'
                teams = [self.safe_text(p) for p in match.select('.styles_participantsNames__-aY7w p')[:2]]
                matched = self.safe_text(match.find('span', class_='cursor-help'))

                outcomes = []
                for idx, container in enumerate(match.select('.betContentContainer')[:3], 1):
                    back = container.select_one('.biab_back-0')
                    lay = container.select_one('.biab_lay-0')

                    b_odds = self.safe_text(back.select_one('.styles_betOdds__bxapE')) if back else 'N/A'
                    b_amt = self.safe_text(back.select_one('.biab_bet-amount')) if back else 'N/A'
                    l_odds = self.safe_text(lay.select_one('.styles_betOdds__bxapE')) if lay else 'N/A'
                    l_amt = self.safe_text(lay.select_one('.biab_bet-amount')) if lay else 'N/A'

                    outcome = '1' if idx == 1 else 'X' if idx == 2 else '2'
                    outcomes.append({
                        'outcome': outcome,
                        'back_odds': b_odds,
                        'back_amount': b_amt,
                        'lay_odds': l_odds,
                        'lay_amount': l_amt
                    })

                data.append({
                    'time_str': time_str,
                    'minutes': minutes,
                    'team1': teams[0],
                    'team2': teams[1],
                    'score': score,
                    'matched': matched,
                    'outcomes': outcomes
                })

            if verbose:
                self.print_data(data)

        except Exception as e:
            print(f"\n❌ Scraping error: {str(e)}")
        finally:
            # Only close the browser if we created it in this call.
            if created_browser and browser:
                await browser.close()
        return data

    def print_data(self, data):
        """Prints scraped data to console in human-readable format."""
        print(f"\n🏆 Live Matches ({len(data)} found) {datetime.now().strftime('%H:%M:%S')}\n{'═' * 50}")
        for match in data:
            print(f"\n⚽ {match['team1']} vs {match['team2']}")
            print(f"⏱️ {match['time_str']}' | 📊 {match['score']} | 💰 {match['matched']}")
            print(f"{'─' * 50}")
            for outcome in match['outcomes']:
                print(
                    f"│ {outcome['outcome']} │ Back: {outcome['back_odds']:<5} ({outcome['back_amount']:<3}) │ Lay: {outcome['lay_odds']:<5} ({outcome['lay_amount']:<3}) │")
            print(f"╰─────────────────────────────────────────────╯")

    def save_data(self, data):
        """Overwrites file with latest data on each update"""
        if not data:
            return
        try:
            filename = os.path.join('D:/autochrome/gdata', 'orbitx_latest.json')  # Fixed filename

            # Write fresh data instead of appending
            with open(filename, 'w', encoding='utf-8') as f:
                timestamp = datetime.now().isoformat()
                for match in data:
                    entry = {'timestamp': timestamp, 'match_data': match}
                    f.write(json.dumps(entry) + '\n')

            print(f"✅ Successfully OVERWROTE {len(data)} matches to {filename}")
        except Exception as e:
            print(f"❌ Error saving data: {str(e)}")

    async def _run_continuous(self, interval, verbose, page=None):
        """Async continuous scraping loop.
           If a page is provided, that page is used on every scrape.
        """
        while True:
            data = await self.scrape_once(verbose=verbose, page=page)
            self.save_data(data)
            await asyncio.sleep(interval)

    # Optional blocking runner for standalone testing
    def run_continuous(self, interval=60, verbose=True):
        asyncio.run(self._run_continuous(interval, verbose))


if __name__ == "__main__":
    scraper = OrbitXScraper()
    scraper.run_continuous(interval=30)
