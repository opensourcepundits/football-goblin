import asyncio
from fastapi import FastAPI, HTTPException, Path
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
import uvicorn
import logging
from urllib.parse import urljoin

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Transfermarkt Detailed API - Teams",
    version="3.0.0"
)

BASE_URL = "https://www.transfermarkt.com"

# Global Dictionary for the teams
TEAMS_CACHE = {
    "south africa": "https://www.transfermarkt.com/suedafrika/startseite/verein/3433",
    "australia": "https://www.transfermarkt.com/australien/startseite/verein/3433/saison_id/2025",
    "mexico": "https://www.transfermarkt.com/mexiko/kader/verein/6303/saison_id/2026"
}

async def fetch_player_details(session: AsyncSession, player_url: str) -> dict:
    """Fetches detailed info from the individual player's profile page."""
    try:
        logger.info(f"Fetching player details: {player_url}")
        response = await session.get(player_url, timeout=15.0)
        if response.status_code != 200:
            return {"error": f"Failed to fetch. Status: {response.status_code}"}
        
        soup = BeautifulSoup(response.text, "lxml")
        details = {}
        
        # 1. Extract standard player data (Name, DOB, Height, Foot, Club, Contract, etc.)
        labels = soup.find_all("span", class_=lambda c: c and "info-table__content--regular" in c)
        for label in labels:
            key = label.text.strip().replace(":", "").strip()
            value_span = label.find_next_sibling("span", class_=lambda c: c and "info-table__content--bold" in c)
            if value_span:
                details[key] = " ".join(value_span.text.split())
        
        # 2. Transfer History extraction
        transfers = []
        transfer_rows = soup.find_all("div", class_=lambda c: c and "tm-player-transfer-history-grid__link" in c)
        for row in transfer_rows:
            cols = row.find_all("div")
            if len(cols) >= 6:
                transfers.append({
                    "season": cols[0].text.strip(),
                    "date": cols[1].text.strip(),
                    "left_club": cols[2].text.strip(),
                    "joined_club": cols[3].text.strip(),
                    "market_value": cols[4].text.strip(),
                    "fee": cols[5].text.strip()
                })
                
        if transfers:
            details["Transfer history"] = transfers

        return details
    except Exception as e:
        logger.error(f"Error fetching {player_url}: {str(e)}")
        return {"error": str(e)}

async def fetch_team_data(session: AsyncSession, country_name: str, team_url: str) -> dict:
    """Helper function to fetch all players and their details for a specific team."""
    logger.info(f"Fetching team roster for {country_name.title()}: {team_url}")
    response = await session.get(team_url, timeout=15.0)
    
    if response.status_code != 200:
        logger.error(f"Failed to fetch team page for {country_name}. Status: {response.status_code}")
        return {"country": country_name.title(), "error": "Could not load team page."}
    
    soup = BeautifulSoup(response.text, "lxml")
    base_players = []
    seen_players = set()
    
    tables = soup.find_all("table", class_="items")
    if not tables:
        logger.warning(f"No player tables found for {country_name}.")
        return {"country": country_name.title(), "squad_size": 0, "players": []}
    
    for table in tables:
        rows = table.find_all("tr", class_=["odd", "even"])
        for row in rows:
            hauptlink = row.find("td", class_="hauptlink")
            if not hauptlink:
                continue
                
            name_tag = hauptlink.find("a", href=True)
            if not name_tag or "/profil/spieler/" not in name_tag["href"]:
                continue
                
            player_name = name_tag.text.strip()
            if player_name in seen_players:
                continue
            seen_players.add(player_name)
            
            player_url = urljoin(BASE_URL, name_tag["href"])
            base_players.append({
                "name": player_name,
                "profile_url": player_url
            })

    logger.info(f"Found {len(base_players)} players for {country_name.title()}. Fetching details...")
    
    # Throttle to max 3 simultaneous requests to avoid IP Ban
    semaphore = asyncio.Semaphore(3) 
    
    async def bounded_fetch(player):
        async with semaphore:
            await asyncio.sleep(1.0) # 1 sec delay to mimic human browsing
            details = await fetch_player_details(session, player["profile_url"])
            player["detailed_info"] = details
            return player

    tasks = [bounded_fetch(p) for p in base_players]
    final_players = await asyncio.gather(*tasks)

    return {
        "country": country_name.title(),
        "team_url": team_url,
        "squad_size": len(final_players),
        "players": final_players
    }


@app.get("/get_all")
async def get_all_teams():
    """Endpoint 1: Fetch details for ALL countries in the dictionary sequentially."""
    results = []
    
    async with AsyncSession(impersonate="chrome") as session:
        # We loop through each country in the cache
        for country, url in TEAMS_CACHE.items():
            team_data = await fetch_team_data(session, country, url)
            results.append(team_data)
            
    return {
        "total_teams_processed": len(results),
        "teams": results
    }

@app.get("/get_specific/{country_name}")
async def get_specific_team(
    country_name: str = Path(..., description="The name of the country (e.g., South Africa, Australia, Mexico)")
):
    """Endpoint 2: Fetch details for a SPECIFIC country by name."""
    country_key = country_name.lower().strip()
    
    if country_key not in TEAMS_CACHE:
        raise HTTPException(
            status_code=404, 
            detail=f"Country '{country_name}' not found. Valid options are: {list(TEAMS_CACHE.keys())}"
        )
        
    team_url = TEAMS_CACHE[country_key]
    
    async with AsyncSession(impersonate="chrome") as session:
        team_data = await fetch_team_data(session, country_key, team_url)
        
    return team_data

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)