"""Classify a tkxel.com URL path into a content category by its prefix."""

# Order matters: first matching prefix wins.
RULES = [
    ("/blog", "Blogs"),
    ("/blogs", "Blogs"),
    ("/case-studies", "Case Studies"),
    ("/case-study", "Case Studies"),
    ("/portfolio", "Case Studies"),
    ("/services", "Services"),
    ("/solutions", "Solutions"),
    ("/industries", "Industries"),
    ("/technologies", "Technologies"),
    ("/about", "Company"),
    ("/careers", "Company"),
    ("/contact", "Company"),
    ("/resources", "Resources"),
    ("/ebooks", "Resources"),
    ("/whitepapers", "Resources"),
]


def categorize(path: str | None) -> str:
    if not path:
        return "Other"
    p = path.lower().split("?")[0].rstrip("/")
    if p == "" or p == "/":
        return "Homepage"
    for prefix, label in RULES:
        if p == prefix or p.startswith(prefix + "/"):
            return label
    return "Other"
