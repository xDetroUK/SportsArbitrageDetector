import asyncio
import json
import re
from pyppeteer import launch
from bs4 import BeautifulSoup
from datetime import datetime


class LiveWinBetMonitor:
    def __init__(self):
        self.browser = None
        self.page = None
        self.file_path = "D:/autochrome/gdata/winbet_odds.json"
        self.url = "https://winbet.bg/in-play?sportId=soccer-1001"

    async def initialize_browser(self):
        """Launch browser and open WinBet live page."""
        self.browser = await launch(
            headless=True,
            executablePath=r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--start-maximized'  # Add this argument to maximize the window
            ],
            defaultViewport=None  # This helps but isn't always enough
        )
        self.page = await self.browser.newPage()

        # Set explicit viewport size
        await self.page.setViewport({"width": 1920, "height": 1080})

        await self.page.setUserAgent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        await self.page.goto(self.url, {'waitUntil': 'networkidle2', 'timeout': 60000})
        print("✅ Browser initialized and WinBet page loaded.")

    def parse_time(self, time_str):
        """Convert time format to minutes."""
        time_str = time_str.strip()

        if any(x in time_str.lower() for x in ['half', 'полувреме', 'ht']):
            return 45

        match = re.search(r'(\d+):\d+', time_str)
        if match:
            return int(match.group(1))

        match = re.search(r'\d+', time_str)
        return int(match.group(0)) if match else 0

    async def extract_live_matches(self):
        """Extract updated odds dynamically without refreshing."""
        try:
            content = await self.page.evaluate('document.documentElement.outerHTML')
            soup = BeautifulSoup(content, 'html.parser')

            matches = []
            for match in soup.select('div.egtd-s-accordion--level-2'):
                try:
                    teams = [t.get_text(strip=True) for t in match.select('span.team')[:2]]
                    scores = [s.get_text(strip=True) for s in match.select('div.score')[:2]]
                    score = f"{scores[0]}-{scores[1]}" if len(scores) == 2 else 'N/A-N/A'

                    time_element = match.select_one('span.egtd-s-clock, span.part.event-meta__item')
                    time_str = time_element.get_text(strip=True) if time_element else 'N/A'

                    odds = [odd.get_text(strip=True) for odd in match.select('span.egtd-odds__odd')[:3]]
                    if len(odds) < 3:
                        odds += ['N/A'] * (3 - len(odds))

                    match_data = {
                        'teams': teams,
                        'score': score,
                        'time': time_str,
                        'minutes': self.parse_time(time_str),
                        'odds': odds,
                        'timestamp': datetime.now().strftime('%H:%M:%S')
                    }
                    matches.append(match_data)
                except Exception as e:
                    print(f"⚠️ Error parsing match: {e}")

            return sorted(matches, key=lambda x: x['minutes'], reverse=True)
        except Exception as e:
            print(f"⚠️ Data extraction error: {e}")
            return []

    def save_to_file(self, matches):
        """Save live match data to JSON file."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as file:
                json.dump(matches, file, indent=4, ensure_ascii=False)
            print(f"💾 Data saved to {self.file_path}")
        except Exception as e:
            print(f"⚠️ Error saving file: {e}")

    def display_matches(self, matches):
        """Print extracted matches in a readable format."""
        print(f"\n{datetime.now().strftime('%H:%M:%S')} 📊 LIVE BETTING UPDATE")
        print("═" * 70)

        for match in matches:
            print(f"\n⚽ {match['teams'][0]} vs {match['teams'][1]}")
            print(f"⏰ Time: {match['time']} | 📍 Score: {match['score']}")
            print("-" * 70)

            if any(odd != 'N/A' for odd in match['odds']):
                print(f"│ 1 │ {match['odds'][0]:<7} │ X │ {match['odds'][1]:<7} │ 2 │ {match['odds'][2]:<7} │")
            else:
                print("│ Odds currently unavailable")

            print("╰" + "─" * 66 + "╯")

    async def gatherbets(self):
        """Continuously monitor live bets without refreshing the page."""
        await self.initialize_browser()

        try:
            while True:
                matches = await self.extract_live_matches()
                self.display_matches(matches)
                self.save_to_file(matches)
                await asyncio.sleep(15)  # Adjust refresh rate as needed
        except Exception as e:
            print(f"❌ Critical error: {e}")
        finally:
            await self.browser.close()
            print("🛑 Browser closed.")


if __name__ == "__main__":
    monitor = LiveWinBetMonitor()
    try:
        asyncio.run(monitor.gatherbets())
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
