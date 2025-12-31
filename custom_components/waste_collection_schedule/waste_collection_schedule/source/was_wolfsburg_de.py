import re
from datetime import datetime

import requests
from waste_collection_schedule import Collection  # type: ignore[attr-defined]
from waste_collection_schedule.exceptions import (
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Wolfsburger Abfallwirtschaft und Straßenreinigung"
DESCRIPTION = "Source for waste collections for WAS-Wolfsburg, Germany."
URL = "https://was-wolfsburg.de"
TEST_CASES = {
    "Wolfsburg": {"street": "Bahnhofspassage", "number": 2},
    "Sülfeld": {"street": "Bärheide", "number": 1},
}

ICON_MAP = {
    "Wertstofftonne": "mdi:recycle",
    "Bioabfall": "mdi:leaf",
    "Restabfall": "mdi:trash-can",
    "Altpapier": "mdi:file-document-outline",
}

class Source:
    def __init__(self, street: str, number: str | int):
        self._street = street
        self._number = str(number)

    def fetch(self) -> list[Collection]:
        # Retrieve authentication token from JavaScript file
        # The API requires a token which is embedded in the main.js file
        js = requests.get("https://abfuhrtermine.waswob.de/js/main.js")
        js.raise_for_status()
        
        token = re.search(r"token=([^\"\n\`]*)", js.text)
        if token is None:
            raise ValueError("Token not found in JavaScript file")

        # Query collection dates for the specified address
        r = requests.get(
            "https://apiabfuhrtermine.waswob.de/api/download-json",
            params={
                "strasse": self._street,
                "hausnummer": self._number,
                "token": token.group(1),
            },
        )
        
        # Handle HTTP errors with better context
        if r.status_code == 500:
            # Server error usually means invalid street or house number
            # Fetch available streets to provide suggestions
            streets_response = requests.get(
                "https://apiabfuhrtermine.waswob.de/api/download-strassen",
                params={"token": token.group(1)},
            )
            streets_response.raise_for_status()
            streets_data = streets_response.json()
            
            # Check if street exists
            street_found = None
            for street_info in streets_data.values():
                if street_info["strName"] == self._street:
                    street_found = street_info
                    break
            
            if not street_found:
                # Street not found - provide suggestions
                available_streets = sorted([s["strName"] for s in streets_data.values()])
                raise SourceArgumentNotFoundWithSuggestions(
                    "street", self._street, list(available_streets)
                )
            else:
                # Street found but house number invalid
                available_numbers = sorted(
                    street_found["Hausnummer"], 
                    key=lambda x: int(''.join(filter(str.isdigit, x)) or '0')
                )
                raise SourceArgumentNotFoundWithSuggestions(
                    "number", self._number, list(available_numbers)
                )
        
        r.raise_for_status()
        
        data = r.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            raise ValueError(f"No collection data found for {self._street} {self._number}")

        entries = []
        
        # API returns a dictionary with waste types as keys and dates as nested dictionaries
        # Format: {"Restabfall": {"2026-01-05": "", "2026-01-19": "Feiertagsverschiebung"}, ...}
        # Not all addresses have all waste types (e.g., some only have Bioabfall)
        for waste_type, icon in ICON_MAP.items():
            if waste_type in data[0]:  # Check if this waste type exists for this address
                for date_str in data[0][waste_type].keys():
                    entries.append(
                        Collection(
                            date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                            t=waste_type,
                            icon=icon,
                        )
                    )

        return entries
