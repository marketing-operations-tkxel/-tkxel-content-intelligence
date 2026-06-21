"""Map GA4 geo.country values to the dashboard's regions.

Anything unmapped falls into 'Other'. GSC property-level rows with no country
are attributed to 'Global'.
"""

COUNTRY_TO_REGION = {
    "United States": "USA",
    "United Kingdom": "UK",
    "Canada": "Canada",
    "Australia": "Australia",
    "United Arab Emirates": "Middle East",
    "Saudi Arabia": "Middle East",
    "Qatar": "Middle East",
    "Kuwait": "Middle East",
    "Bahrain": "Middle East",
    "Oman": "Middle East",
    "Pakistan": "South Asia",
    "India": "South Asia",
    "Bangladesh": "South Asia",
    "Germany": "Europe",
    "France": "Europe",
    "Netherlands": "Europe",
    "Ireland": "Europe",
    "Spain": "Europe",
    "Italy": "Europe",
    "Singapore": "APAC",
    "Malaysia": "APAC",
    "Philippines": "APAC",
}

# The set of regions the frontend filter offers (plus 'All').
REGIONS = ["USA", "UK", "Canada", "Australia", "Middle East",
           "South Asia", "Europe", "APAC", "Other"]


def region_for(country: str | None) -> str:
    if not country:
        return "Other"
    return COUNTRY_TO_REGION.get(country.strip(), "Other")
