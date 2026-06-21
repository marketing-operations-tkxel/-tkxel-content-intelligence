"""Region bucketing for the rich dashboard: USA / MENA / Europe / RoW.

GA4 geo.country uses full English names; GSC uses ISO-3166 alpha-3 codes.
Both are expressed as SQL CASE snippets so the grouping happens in BigQuery.
"""

# GA4 (full country names)
GA4_REGION_CASE = """
CASE
  WHEN geo.country = 'United States' THEN 'USA'
  WHEN geo.country IN ('United Arab Emirates','Saudi Arabia','Egypt','Qatar','Kuwait',
       'Bahrain','Oman','Jordan','Lebanon','Iraq','Morocco','Tunisia','Algeria',
       'Israel','Palestine','Yemen','Libya','Syria') THEN 'MENA'
  WHEN geo.country IN ('United Kingdom','Germany','Netherlands','Ireland','France','Spain',
       'Italy','Poland','Belgium','Sweden','Switzerland','Denmark','Norway','Austria',
       'Portugal','Finland','Czechia','Romania','Greece','Hungary','Ukraine','Latvia',
       'Lithuania','Estonia','Luxembourg','Bulgaria','Croatia','Slovakia','Slovenia',
       'Serbia','Iceland') THEN 'Europe'
  ELSE 'RoW'
END
"""

# GSC (alpha-3 lowercase)
GSC_REGION_CASE = """
CASE
  WHEN country = 'usa' THEN 'USA'
  WHEN country IN ('are','sau','egy','qat','kwt','bhr','omn','jor','lbn','irq','mar',
       'tun','dza','isr','pse','yem','lby','syr') THEN 'MENA'
  WHEN country IN ('gbr','deu','nld','irl','fra','esp','ita','pol','bel','swe','che',
       'dnk','nor','aut','prt','fin','cze','rou','grc','hun','ukr','lva','ltu','est',
       'lux','bgr','hrv','svk','svn','srb','isl') THEN 'Europe'
  ELSE 'RoW'
END
"""

# Content category from a normalized path (column alias `p`)
CATEGORY_CASE = """
CASE
  WHEN p = '' OR p = '/' THEN 'Home/Root'
  WHEN REGEXP_CONTAINS(p, r'^/services') THEN 'Service Pages'
  WHEN REGEXP_CONTAINS(p, r'^/blogs?(/|$)') THEN 'Blogs'
  WHEN REGEXP_CONTAINS(p, r'^/webinars?(/|$)') THEN 'Webinars'
  WHEN REGEXP_CONTAINS(p, r'^/white-papers?(/|$)') THEN 'White Papers & Reports'
  WHEN REGEXP_CONTAINS(p, r'^/podcast') THEN 'Podcasts'
  WHEN REGEXP_CONTAINS(p, r'^/(about|company|careers|contact|our-customers|how-we-work|press-kit|leadership|partners|our-team)') THEN 'Other/Corporate'
  ELSE 'Other Content'
END
"""

# LLM source from a lowercased host/source string (column alias `h`)
LLM_SOURCE_CASE = """
CASE
  WHEN h LIKE '%chatgpt%' OR h LIKE '%chat.openai%' OR h LIKE '%openai%' THEN 'ChatGPT'
  WHEN h LIKE '%gemini%' OR h LIKE '%bard.google%' THEN 'Gemini'
  WHEN h LIKE '%claude%' THEN 'Claude'
  WHEN h LIKE '%perplexity%' THEN 'Perplexity'
  WHEN h LIKE '%copilot%' OR h LIKE '%bing.com/chat%' OR h LIKE '%bingchat%' THEN 'Copilot'
  ELSE NULL
END
"""

REGIONS = ["USA", "MENA", "Europe", "RoW"]
LLM_SOURCES = ["ChatGPT", "Gemini", "Claude", "Perplexity", "Copilot"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
