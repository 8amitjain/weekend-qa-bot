"""
Weekend QA Audit — GitHub Actions + Vercel Cron Serverless Function.
Runs every Saturday at 8am EST (1pm UTC).
Checks all active sites across PharmaxaLabs / Solvaderm / Nuu3,
generates a PDF report, and posts to Slack #automated-qc.

Updated: 2026-04-16 — synced with Google Sheets site list + product priority.
"""

from http.server import BaseHTTPRequestHandler
import requests as req
import ssl
import socket
import re
import time
import json
import os
import io
import sys
import traceback
import concurrent.futures
from urllib.parse import urlparse
from datetime import datetime, timezone

# ── Config ───────────────────────────────────────────────────────────────

TIMEOUT = 10
MAX_WORKERS = 15
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "C0AP3RF4J4B")
AMIT_ID = "U05K6HRC4V6"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
HDRS = {"User-Agent": UA}

# ── Product Priority (from Priority Sheet — revenue-ranked) ─────────────
# Used to weight which sites get deeper audits and appear first in reports.
PRODUCT_PRIORITY = {
    "Virectin": 1, "Flexoplex": 2, "Provasil": 3, "Phenocal": 4,
    "Zenotone": 5, "Stemuderm": 6, "Nutesta": 7, "Prostara": 8,
    "Glucoeze": 9, "Menoquil": 10, "Natures Superfuel": 11,
    "Stemnucell": 12, "Vazopril": 13, "Nufolix": 14, "Eyevage": 15,
    "Ocuvital": 16, "ACV Gummies": 17, "Ace Ferulic": 18,
    "Gut Health 365": 19, "Revivatone": 20, "Somulin": 21,
    "Juvabrite": 22, "Serelax": 23, "Sleep Support": 24,
    "Colopril": 25, "Flexdermal": 26, "Zenofem": 27,
    "Zenogel": 28, "Bonexcin": 29, "Maxolean": 30,
    "Endmigra": 31, "UTM": 32, "Liver Health 365": 33,
    "Greenpura": 34,
}

# ── Site Lists (synced from Google Sheets 2026-04-16) ────────────────────
# Categories: shopify (main stores), tld (top-level domains),
#   kill (Google Adwords funnel pages), solv_kill, nuu3_kill,
#   ppc (PBN for Google Adwords), seo (PBN SEO sites),
#   redirect (301 SEO domains on Shopify)

# TIER 1 — Main Shopify Stores + Top Priority Kill Pages + Top TLDs
TIER1 = [
    # Main Shopify Stores (checkout domains)
    {"url": "https://www.virectin.com/", "cat": "shopify", "label": "Virectin Store (#1)", "priority": 1},
    {"url": "https://www.flexoplex.com/", "cat": "shopify", "label": "Flexoplex Store (#2)", "priority": 2},
    {"url": "https://www.provasil.com/", "cat": "shopify", "label": "Provasil Store (#3)", "priority": 3},
    {"url": "https://www.phenocal.com/", "cat": "shopify", "label": "Phenocal Store (#4)", "priority": 4},
    {"url": "https://www.menoquil.com/", "cat": "shopify", "label": "Menoquil Store (#10)", "priority": 10},
    {"url": "https://www.nuu3.com/", "cat": "shopify", "label": "Nuu3 Store", "priority": 11},
    {"url": "https://www.solvadermstore.com/", "cat": "shopify", "label": "Solvaderm Store (#6)", "priority": 6},
    {"url": "https://www.pharmaxalabs.com/", "cat": "shopify", "label": "PharmaxaLabs Store", "priority": 1},

    # Top Kill Pages (revenue-priority order)
    {"url": "https://www.virectinstore.com/", "cat": "kill", "label": "Virectin Kill (#1)", "priority": 1},
    {"url": "https://www.flexoplexstore.com/", "cat": "kill", "label": "Flexoplex Kill (#2)", "priority": 2},
    {"url": "https://www.provasilstore.com/", "cat": "kill", "label": "Provasil Kill (#3)", "priority": 3},
    {"url": "https://www.phenocalstore.com/", "cat": "kill", "label": "Phenocal Kill (#4)", "priority": 4},
    {"url": "https://www.menoquilstore.com/", "cat": "kill", "label": "Menoquil Kill (#10)", "priority": 10},
    {"url": "https://products.solvadermstore.com/stemuderm/", "cat": "solv_kill", "label": "Stemuderm Kill (#6)", "priority": 6},
    {"url": "https://products.solvadermstore.com/eyevage/", "cat": "solv_kill", "label": "Eyevage Kill (#15)", "priority": 15},

    # Top TLDs by revenue
    {"url": "https://www.zenotone.com/", "cat": "tld", "label": "Zenotone (#5)", "priority": 5},
    {"url": "https://www.nutesta.com/", "cat": "tld", "label": "Nutesta (#7)", "priority": 7},
    {"url": "https://www.prostara.com/", "cat": "tld", "label": "Prostara (#8)", "priority": 8},
    {"url": "https://www.glucoeze.com/", "cat": "tld", "label": "Glucoeze (#9)", "priority": 9},
]

# TIER 2 — All remaining TLDs + Kill Pages + Solvaderm/Nuu3 Kill Pages
TIER2 = [
    # TLD Domains (WordPress)
    {"url": "https://www.serelax.com/", "cat": "tld", "label": "Serelax (#23)"},
    {"url": "https://www.somulin.com/", "cat": "tld", "label": "Somulin (#21)"},
    {"url": "https://www.colopril.com/", "cat": "tld", "label": "Colopril (#25)"},
    {"url": "https://www.flexdermal.com/", "cat": "tld", "label": "Flexdermal (#26)"},
    {"url": "https://www.zenofem.com/", "cat": "tld", "label": "Zenofem (#27)"},
    {"url": "https://www.zenogel.com/", "cat": "tld", "label": "Zenogel (#28)"},
    {"url": "https://www.bonexcin.com/", "cat": "tld", "label": "Bonexcin (#29)"},
    {"url": "https://www.nufolix.com/", "cat": "tld", "label": "Nufolix (#14)"},
    {"url": "https://www.ocuvital.com/", "cat": "tld", "label": "Ocuvital (#16)"},
    {"url": "https://www.maxolean.com/", "cat": "tld", "label": "Maxolean (#30)"},
    {"url": "https://www.endmigra.com/", "cat": "tld", "label": "Endmigra (#31)"},
    {"url": "https://www.greenpura.com/", "cat": "tld", "label": "Greenpura (#34)"},
    {"url": "https://www.vazopril.com/", "cat": "tld", "label": "Vazopril (#13)"},

    # Duplicate / alternate TLD stores
    {"url": "https://www.colopril.us/", "cat": "tld", "label": "Colopril US"},
    {"url": "https://www.bonexcin.us/", "cat": "tld", "label": "Bonexcin US"},
    {"url": "https://www.somulin.store/", "cat": "tld", "label": "Somulin Store"},
    {"url": "https://www.myprovasil.com/", "cat": "tld", "label": "MyProvasil"},
    {"url": "https://www.vazoprilstore.com/", "cat": "tld", "label": "Vazopril Store"},
    {"url": "https://www.serelaxstore.com/", "cat": "tld", "label": "Serelax Store"},
    {"url": "https://www.prostarastore.com/", "cat": "tld", "label": "Prostara Store"},
    {"url": "https://www.flexdermalstore.com/", "cat": "tld", "label": "Flexdermal Store"},
    {"url": "https://www.zenofemstore.com/", "cat": "tld", "label": "Zenofem Store"},
    {"url": "https://nuu3supergreens.com/", "cat": "tld", "label": "Nuu3 Super Greens"},

    # PharmaxaLabs subdomain Kill Pages
    {"url": "https://menoquil.pharmaxalabs.com/", "cat": "kill", "label": "Menoquil Kill Sub"},
    {"url": "https://provasil.pharmaxalabs.com/", "cat": "kill", "label": "Provasil Kill Sub"},
    {"url": "https://serelax.pharmaxalabs.com/", "cat": "kill", "label": "Serelax Kill Sub"},
    {"url": "https://somulin.pharmaxalabs.com/", "cat": "kill", "label": "Somulin Kill Sub"},
    {"url": "https://prostara.pharmaxalabs.com/", "cat": "kill", "label": "Prostara Kill Sub"},
    {"url": "https://colopril.pharmaxalabs.com/", "cat": "kill", "label": "Colopril Kill Sub"},
    {"url": "https://flexdermal.pharmaxalabs.com/", "cat": "kill", "label": "Flexdermal Kill Sub"},
    {"url": "https://zenofem.pharmaxalabs.com/", "cat": "kill", "label": "Zenofem Kill Sub"},
    {"url": "https://zenogel.pharmaxalabs.com/", "cat": "kill", "label": "Zenogel Kill Sub"},
    {"url": "https://bonexcin.pharmaxalabs.com/", "cat": "kill", "label": "Bonexcin Kill Sub"},
    {"url": "https://vazopril.pharmaxalabs.com/", "cat": "kill", "label": "Vazopril Kill Sub"},
    {"url": "https://glucoeze.pharmaxalabs.com/", "cat": "kill", "label": "Glucoeze Kill Sub"},
    {"url": "https://nufolix.pharmaxalabs.com/", "cat": "kill", "label": "Nufolix Kill Sub"},
    {"url": "https://nutesta.pharmaxalabs.com/", "cat": "kill", "label": "Nutesta Kill Sub"},
    {"url": "https://ocuvital.pharmaxalabs.com/", "cat": "kill", "label": "Ocuvital Kill Sub"},
    {"url": "https://zenotone.pharmaxalabs.com/", "cat": "kill", "label": "Zenotone Kill Sub"},
    {"url": "https://maxolean.pharmaxalabs.com/", "cat": "kill", "label": "Maxolean Kill Sub"},
    {"url": "https://endmigra.pharmaxalabs.com/", "cat": "kill", "label": "Endmigra Kill Sub"},

    # Solvaderm Subdomain Kill Pages
    {"url": "https://products.solvadermstore.com/", "cat": "solv_kill", "label": "Solvaderm Products Hub"},
    {"url": "https://products.solvadermstore.com/ace-ferulic/", "cat": "solv_kill", "label": "Ace Ferulic Kill (#18)"},
    {"url": "https://products.solvadermstore.com/stemnucell/", "cat": "solv_kill", "label": "Stemnucell Kill (#12)"},
    {"url": "https://products.solvadermstore.com/revivatone/", "cat": "solv_kill", "label": "Revivatone Kill (#20)"},
    {"url": "https://products.solvadermstore.com/juvabrite/", "cat": "solv_kill", "label": "Juvabrite Kill (#22)"},
    {"url": "https://products.solvadermstore.com/universal-tinted-moisturizer/", "cat": "solv_kill", "label": "UTM Kill (#32)"},

    # Nuu3 Subdomain Kill Pages
    {"url": "https://products.nuu3.com/", "cat": "nuu3_kill", "label": "Nuu3 Products Hub"},
    {"url": "https://products.nuu3.com/natures-superfuel/", "cat": "nuu3_kill", "label": "Superfuel Kill (#11)"},
    {"url": "https://products.nuu3.com/acv-gummies/", "cat": "nuu3_kill", "label": "ACV Gummies Kill (#17)"},
    {"url": "https://products.nuu3.com/gut-health-365/", "cat": "nuu3_kill", "label": "Gut Health Kill (#19)"},
    {"url": "https://products.nuu3.com/sleep-support-gummies/", "cat": "nuu3_kill", "label": "Sleep Support Kill (#24)"},
    {"url": "https://products.nuu3.com/liver-health-365/", "cat": "nuu3_kill", "label": "Liver Health Kill (#33)"},
]

# TIER 3 — PPC, SEO sites, and 301 redirect domains
TIER3 = [
    # PPC Domains (PBN for Google Adwords)
    {"url": "https://www.totalhealthreports.us/", "cat": "ppc", "label": "Total Health Reports"},
    {"url": "https://blog.totalhealthreports.us/", "cat": "ppc", "label": "THR Blog"},
    {"url": "https://news.totalhealthreports.us/", "cat": "ppc", "label": "THR News"},
    {"url": "https://beauty.totalhealthreports.us/", "cat": "ppc", "label": "THR Beauty"},
    {"url": "https://reviews.totalhealthreports.us/", "cat": "ppc", "label": "THR Reviews"},
    {"url": "https://nutrition.totalhealthreports.us/", "cat": "ppc", "label": "THR Nutrition"},
    {"url": "https://www.trustedhealthanswers.com/", "cat": "ppc", "label": "Trusted Health Answers"},

    # SEO Sites (PBN)
    {"url": "https://www.healthwebmagazine.com/", "cat": "seo", "label": "Health Web Magazine"},
    {"url": "https://www.skinformulations.com/", "cat": "seo", "label": "Skin Formulations"},
    {"url": "https://www.virectin.us/", "cat": "seo", "label": "Virectin US"},
    {"url": "https://www.totalhealthreports.com/", "cat": "seo", "label": "THR .com"},
    {"url": "https://staging.healthwebmagazine.com/", "cat": "seo", "label": "HWM Staging"},
    {"url": "https://memoforce.online/", "cat": "seo", "label": "Memoforce"},
    {"url": "https://prostastream.online/", "cat": "seo", "label": "ProstaStream"},
    {"url": "https://prostastreamreviews.com/", "cat": "seo", "label": "ProstaStream Reviews"},
    {"url": "https://totalshoppingdigest.com/", "cat": "seo", "label": "Total Shopping Digest"},
    {"url": "https://healthnewsadvisors.com/", "cat": "seo", "label": "Health News Advisors"},

    # WordPress / Backup sites
    {"url": "https://blog.pharmaxalabs.com/", "cat": "seo", "label": "PharmaxaLabs Blog"},
    {"url": "https://tinnitus.pharmaxalabs.com/", "cat": "seo", "label": "Tinnitus Sub"},
    {"url": "https://besthealthshopping.us/", "cat": "seo", "label": "Best Health Shopping"},
    {"url": "https://shopping.trustedhealthanswers.com/", "cat": "seo", "label": "THA Shopping"},
    {"url": "https://backup.dailyhealthshopping.com/", "cat": "seo", "label": "Daily Health Backup"},
    {"url": "https://staging.flexoplexstore.com/", "cat": "seo", "label": "Flexoplex Staging"},

    # Shopify 301 Redirect / SEO Domains (light check — just verify redirect works)
    {"url": "https://beyondthetalk.net/", "cat": "redirect", "label": "beyondthetalk.net"},
    {"url": "https://thedailynewsportal.com/", "cat": "redirect", "label": "thedailynewsportal.com"},
    {"url": "https://thierrysanchez.com/", "cat": "redirect", "label": "thierrysanchez.com"},
    {"url": "https://themysticwolf.com/", "cat": "redirect", "label": "themysticwolf.com"},
    {"url": "https://newnaturalbook.com/", "cat": "redirect", "label": "newnaturalbook.com"},
    {"url": "https://shawnboothmeals.com/", "cat": "redirect", "label": "shawnboothmeals.com"},
    {"url": "https://wassupte.com/", "cat": "redirect", "label": "wassupte.com"},
    {"url": "https://5minutehealthfixes.com/", "cat": "redirect", "label": "5minutehealthfixes.com"},
    {"url": "https://supremestrengthforsports.com/", "cat": "redirect", "label": "supremestrengthforsports.com"},
    {"url": "https://bionoricusa.com/", "cat": "redirect", "label": "bionoricusa.com"},
    {"url": "https://casa-tres-amigos-goa.com/", "cat": "redirect", "label": "casa-tres-amigos-goa.com"},
    {"url": "https://daxmoypersonaltrainingstudios.com/", "cat": "redirect", "label": "daxmoypersonaltraining.com"},
    {"url": "https://fromzerotoathlete.com/", "cat": "redirect", "label": "fromzerotoathlete.com"},
    {"url": "https://journalofinfertility.com/", "cat": "redirect", "label": "journalofinfertility.com"},
    {"url": "https://thedietitianchoice.com/", "cat": "redirect", "label": "thedietitianchoice.com"},
    {"url": "https://advancedtrochology.com/", "cat": "redirect", "label": "advancedtrochology.com"},
    {"url": "https://jertong.com/", "cat": "redirect", "label": "jertong.com"},
    {"url": "https://kcstrengthcoaching.com/", "cat": "redirect", "label": "kcstrengthcoaching.com"},
    {"url": "https://metropolitantheclub.com/", "cat": "redirect", "label": "metropolitantheclub.com"},
    {"url": "https://swissnavylube.com/", "cat": "redirect", "label": "swissnavylube.com"},
]


# ── Check Functions ──────────────────────────────────────────────────────

def check_http(url, follow_redirects=True):
    """HTTP status, response time, and HTML content."""
    try:
        start = time.time()
        r = req.get(url, headers=HDRS, timeout=TIMEOUT, allow_redirects=follow_redirects)
        elapsed = round(time.time() - start, 2)
        final_url = r.url if follow_redirects else url
        return {
            "code": r.status_code,
            "time": elapsed,
            "ok": r.status_code == 200,
            "html": r.text,
            "final_url": final_url,
            "redirected": final_url != url,
        }
    except req.exceptions.SSLError as e:
        return {"code": None, "err": f"SSL: {str(e)[:80]}", "ok": False, "html": ""}
    except req.exceptions.ConnectionError as e:
        return {"code": None, "err": f"Conn: {str(e)[:80]}", "ok": False, "html": ""}
    except req.exceptions.Timeout:
        return {"code": None, "err": f"Timeout >{TIMEOUT}s", "ok": False, "html": ""}
    except Exception as e:
        return {"code": None, "err": str(e)[:80], "ok": False, "html": ""}


def check_ssl(url):
    """SSL certificate validity and expiry."""
    hostname = urlparse(url).hostname
    if not hostname:
        return {"ok": False, "err": "Bad host"}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as s:
            with ctx.wrap_socket(s, server_hostname=hostname) as ss:
                cert = ss.getpeercert()
                days = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400
                return {"ok": True, "days": round(days), "warn": days < 30}
    except Exception as e:
        return {"ok": False, "err": str(e)[:60]}


def check_meta(html, url):
    """Meta tags, SEO elements, accessibility basics."""
    issues = []

    # Title
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        t = m.group(1).strip()
        if len(t) < 10:
            issues.append(("warning", f"Title too short ({len(t)} chars)"))
        elif len(t) > 70:
            issues.append(("info", f"Title long ({len(t)} chars, ideal <60)"))
    else:
        issues.append(("critical", "Missing <title> tag"))

    # Meta description
    d = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.I)
    if not d:
        d = re.search(r'<meta\s+content=["\'](.*?)["\']\s+name=["\']description["\']', html, re.I)
    if not d:
        issues.append(("warning", "Missing meta description"))
    elif d and len(d.group(1)) < 50:
        issues.append(("info", f"Meta description short ({len(d.group(1))} chars)"))

    # Viewport
    if not re.search(r'<meta\s+name=["\']viewport["\']', html, re.I):
        issues.append(("critical", "Missing viewport meta (not mobile-friendly)"))

    # H1
    h1s = re.findall(r"<h1[^>]*>", html, re.I)
    if not h1s:
        issues.append(("warning", "Missing H1 tag"))
    elif len(h1s) > 1:
        issues.append(("info", f"Multiple H1 tags ({len(h1s)})"))

    # Canonical
    if not re.search(r'rel=["\']canonical["\']', html, re.I):
        issues.append(("warning", "Missing canonical tag"))

    # Schema / JSON-LD
    if not re.search(r'application/ld\+json', html, re.I):
        issues.append(("info", "No JSON-LD schema markup"))

    # Open Graph
    if not re.search(r'property=["\']og:', html, re.I):
        issues.append(("info", "Missing Open Graph meta tags"))

    # Mixed content
    if url.startswith("https"):
        mc = re.findall(r'(?:src|href)=["\']http://(?!localhost)', html, re.I)
        if mc:
            issues.append(("warning", f"Mixed content: {len(mc)} HTTP resources on HTTPS"))

    # Placeholder text
    if "lorem ipsum" in html.lower():
        issues.append(("critical", "Lorem Ipsum placeholder text found"))
    if "coming soon" in html.lower() and "<title" in html.lower():
        issues.append(("warning", "'Coming soon' text detected"))

    # Images missing alt
    imgs = re.findall(r"<img\s+[^>]*?>", html, re.I)
    no_alt = [i for i in imgs if 'alt=' not in i.lower()]
    if no_alt:
        issues.append(("warning", f"{len(no_alt)}/{len(imgs)} images missing alt text"))

    # Robots meta
    robots = re.search(r'<meta\s+name=["\']robots["\']\s+content=["\']([^"\']*)["\']', html, re.I)
    if robots and 'noindex' in robots.group(1).lower():
        issues.append(("warning", "Page set to noindex"))

    # Favicon
    if not re.search(r'rel=["\'](?:shortcut )?icon["\']', html, re.I):
        issues.append(("info", "Missing favicon link"))

    return issues


def check_links(html, base_url):
    """Check for broken internal links (sample up to 10)."""
    issues = []
    parsed = urlparse(base_url)
    base_domain = parsed.netloc

    # Find internal links
    links = re.findall(r'href=["\']([^"\'#]+)["\']', html, re.I)
    internal = []
    for link in links:
        if link.startswith('/'):
            internal.append(f"{parsed.scheme}://{base_domain}{link}")
        elif base_domain in link:
            internal.append(link)

    # Deduplicate and sample
    internal = list(set(internal))[:10]

    broken = []
    for link in internal:
        try:
            r = req.head(link, headers=HDRS, timeout=5, allow_redirects=True)
            if r.status_code >= 400:
                broken.append(f"{link} → {r.status_code}")
        except Exception:
            broken.append(f"{link} → timeout/error")

    if broken:
        issues.append(("warning", f"Broken links ({len(broken)}): {'; '.join(broken[:3])}"))

    return issues


def audit_site(site, tier):
    """Run all checks for a single site."""
    url = site["url"]
    cat = site["cat"]
    r = {
        "url": url,
        "label": site["label"],
        "cat": cat,
        "tier": tier,
        "issues": [],
        "resp_time": None,
        "priority": site.get("priority", 99),
    }

    try:
        # For redirect domains, just check if redirect works
        if cat == "redirect":
            http = check_http(url, follow_redirects=True)
            if not http["ok"]:
                r["issues"].append(("critical", http.get("err", f"HTTP {http.get('code')}")))
                r["status"] = "DOWN"
            elif not http.get("redirected"):
                r["issues"].append(("warning", "301 domain NOT redirecting — check DNS"))
                r["status"] = "WARNING"
            else:
                r["status"] = "PASS"
            r["resp_time"] = http.get("time")
            return r

        # HTTP check
        http = check_http(url)
        if not http["ok"]:
            r["issues"].append(("critical", http.get("err", f"HTTP {http.get('code')}")))
            r["status"] = "DOWN"
            return r

        r["resp_time"] = http["time"]
        if http["time"] > 5:
            r["issues"].append(("warning", f"Slow response: {http['time']}s"))
        elif http["time"] > 3:
            r["issues"].append(("info", f"Moderate response: {http['time']}s"))

        # SSL check
        s = check_ssl(url)
        if not s["ok"]:
            r["issues"].append(("critical", f"SSL error: {s.get('err', 'failed')}"))
        elif s.get("warn"):
            r["issues"].append(("critical", f"SSL expires in {s['days']} days!"))
        elif s.get("days") and s["days"] < 60:
            r["issues"].append(("warning", f"SSL expires in {s['days']} days"))

        # Meta / SEO checks
        html = http.get("html", "")
        if html:
            r["issues"].extend(check_meta(html, url))

            # Tier 1: deeper checks
            if tier == 1:
                # CTA check for stores/kill pages
                if cat in ("shopify", "kill", "solv_kill", "nuu3_kill"):
                    if not re.search(r"(?:buy.now|add.to.cart|order.now|shop.now|get.started|subscribe)", html, re.I):
                        r["issues"].append(("warning", "No CTA button found (Buy Now / Add to Cart)"))

                # Check internal links
                r["issues"].extend(check_links(html, url))

                # Page size
                kb = len(html) / 1024
                if kb > 500:
                    r["issues"].append(("info", f"Large HTML: {round(kb)}KB"))

                # Check for sitemap reference
                try:
                    sitemap_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}/sitemap.xml"
                    sr = req.get(sitemap_url, headers=HDRS, timeout=5)
                    if sr.status_code != 200:
                        r["issues"].append(("info", "sitemap.xml not found"))
                except Exception:
                    r["issues"].append(("info", "sitemap.xml unreachable"))

                # Check robots.txt
                try:
                    robots_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}/robots.txt"
                    rr = req.get(robots_url, headers=HDRS, timeout=5)
                    if rr.status_code != 200:
                        r["issues"].append(("info", "robots.txt not found"))
                except Exception:
                    pass

        # Determine status
        crits = sum(1 for t, _ in r["issues"] if t == "critical")
        warns = sum(1 for t, _ in r["issues"] if t == "warning")
        r["status"] = "CRITICAL" if crits else ("WARNING" if warns else "PASS")

    except Exception as e:
        print(f"ERROR auditing {url}: {traceback.format_exc()}")
        r["status"] = "ERROR"
        r["issues"].append(("critical", f"Audit crashed: {str(e)[:100]}"))

    return r


# ── Run All ──────────────────────────────────────────────────────────────

def run_audit():
    start = time.time()
    results = {"tier1": [], "tier2": [], "tier3": []}

    # Tier 1: sequential deep audit (most important sites)
    for s in TIER1:
        results["tier1"].append(audit_site(s, 1))

    # Tier 2: parallel standard audit
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(audit_site, s, 2): s for s in TIER2}
        for f in concurrent.futures.as_completed(futs):
            results["tier2"].append(f.result())

    # Tier 3: parallel light audit (PPC, SEO, redirects)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(audit_site, s, 3): s for s in TIER3}
        for f in concurrent.futures.as_completed(futs):
            results["tier3"].append(f.result())

    all_r = results["tier1"] + results["tier2"] + results["tier3"]
    results["summary"] = {
        "total": len(all_r),
        "critical": sum(1 for r in all_r if r["status"] == "CRITICAL"),
        "warning": sum(1 for r in all_r if r["status"] == "WARNING"),
        "passed": sum(1 for r in all_r if r["status"] == "PASS"),
        "down": sum(1 for r in all_r if r["status"] == "DOWN"),
        "errors": sum(1 for r in all_r if r["status"] == "ERROR"),
        "info": sum(1 for r in all_r for t, _ in r["issues"] if t == "info"),
        "issues": sum(len(r["issues"]) for r in all_r),
        "duration": round(time.time() - start),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tier_counts": {
            "tier1": len(results["tier1"]),
            "tier2": len(results["tier2"]),
            "tier3": len(results["tier3"]),
        },
    }
    return results


# ── PDF Generation ───────────────────────────────────────────────────────

def generate_pdf(results):
    try:
        return _generate_pdf_inner(results)
    except Exception as e:
        print(f"ERROR generating PDF: {traceback.format_exc()}")
        return None


def _generate_pdf_inner(results):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, KeepTogether
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "CT", parent=styles["Title"], fontSize=26,
        textColor=HexColor("#1a1a2e"), alignment=TA_CENTER, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "CS", parent=styles["Normal"], fontSize=13,
        textColor=HexColor("#666"), alignment=TA_CENTER, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "SH", parent=styles["Heading1"], fontSize=15,
        textColor=HexColor("#1a1a2e"), spaceBefore=14, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "IT", parent=styles["Normal"], fontSize=9, leading=12,
        spaceBefore=1, spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        "SM", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=HexColor("#888"),
    ))

    s = results["summary"]
    story = []

    # ── Cover Page ──
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("Weekend QA Audit Report", styles["CT"]))
    story.append(Paragraph(
        f"{s['date']} | {s['total']} Sites Checked", styles["CS"],
    ))
    story.append(Paragraph("PharmaxaLabs / Solvaderm / Nuu3", styles["CS"]))
    story.append(Spacer(1, 0.4 * inch))

    stat_data = [
        [
            Paragraph(f"<font size='22'>{s['total']}</font>", styles["CS"]),
            Paragraph(f"<font size='22' color='#c62828'>{s['critical']}</font>", styles["CS"]),
            Paragraph(f"<font size='22' color='#f57f17'>{s['warning']}</font>", styles["CS"]),
            Paragraph(f"<font size='22' color='#2e7d32'>{s['passed']}</font>", styles["CS"]),
            Paragraph(f"<font size='22' color='#b71c1c'>{s['down']}</font>", styles["CS"]),
        ],
        [
            Paragraph("Checked", styles["SM"]),
            Paragraph("Critical", styles["SM"]),
            Paragraph("Warnings", styles["SM"]),
            Paragraph("Passed", styles["SM"]),
            Paragraph("Down", styles["SM"]),
        ],
    ]
    st = Table(stat_data, colWidths=[1.3 * inch] * 5)
    st.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, HexColor("#e0e0e0")),
    ]))
    story.append(st)
    story.append(Spacer(1, 0.2 * inch))
    tc = s.get("tier_counts", {})
    story.append(Paragraph(
        f"Duration: {s['duration']}s | Issues: {s['issues']} | "
        f"T1: {tc.get('tier1', '?')} T2: {tc.get('tier2', '?')} T3: {tc.get('tier3', '?')}",
        styles["SM"],
    ))
    story.append(PageBreak())

    # ── Critical Issues Summary ──
    story.append(Paragraph("Critical Issues Summary", styles["SH"]))
    all_r = results["tier1"] + results["tier2"] + results["tier3"]
    crit_sites = [r for r in all_r if r["status"] in ("CRITICAL", "DOWN")]
    if not crit_sites:
        story.append(Paragraph(
            '<font color="#2e7d32">No critical issues found. All sites operational.</font>',
            styles["IT"],
        ))
    else:
        for site in sorted(crit_sites, key=lambda x: x.get("priority", 99)):
            story.append(Paragraph(
                f'<font color="#c62828">[{site["status"]}]</font> '
                f'<b>{site["label"]}</b> — <font color="#888">{site["url"]}</font>',
                styles["IT"],
            ))
            for typ, msg in site["issues"]:
                if typ == "critical":
                    story.append(Paragraph(
                        f'&nbsp;&nbsp;&nbsp;<font color="#c62828">* {msg[:90]}</font>',
                        styles["IT"],
                    ))
            story.append(Spacer(1, 4))
    story.append(PageBreak())

    # ── Tier Sections ──
    def add_tier(tier_results, name):
        story.append(Paragraph(name, styles["SH"]))
        hdr = ["Site", "Cat", "Status", "Time", "Issues"]
        rows_data = [hdr]
        status_order = {"DOWN": 0, "CRITICAL": 1, "WARNING": 2, "PASS": 3}
        for site in sorted(tier_results, key=lambda x: (
            status_order.get(x["status"], 4), x.get("priority", 99)
        )):
            rt = f"{site['resp_time']}s" if site.get("resp_time") else "N/A"
            ci = sum(1 for t, _ in site["issues"] if t == "critical")
            wi = sum(1 for t, _ in site["issues"] if t == "warning")
            isum = []
            if ci:
                isum.append(f"{ci}C")
            if wi:
                isum.append(f"{wi}W")
            sc = {
                "CRITICAL": "#c62828", "WARNING": "#f57f17",
                "PASS": "#2e7d32", "DOWN": "#b71c1c",
            }.get(site["status"], "#888")
            cat_short = site["cat"][:6]
            rows_data.append([
                Paragraph(f'<font size="8">{site["label"][:35]}</font>', styles["IT"]),
                Paragraph(f'<font size="7" color="#888">{cat_short}</font>', styles["IT"]),
                Paragraph(f'<font size="8" color="{sc}">[{site["status"]}]</font>', styles["IT"]),
                Paragraph(f'<font size="8">{rt}</font>', styles["IT"]),
                Paragraph(f'<font size="8">{" / ".join(isum) if isum else "Clean"}</font>', styles["IT"]),
            ])
        t = Table(rows_data, colWidths=[2.2 * inch, 0.6 * inch, 1.0 * inch, 0.7 * inch, 1.0 * inch], repeatRows=1)
        ts = [
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e0e0e0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]
        for i in range(2, len(rows_data), 2):
            ts.append(("BACKGROUND", (0, i), (-1, i), HexColor("#f5f5f5")))
        t.setStyle(TableStyle(ts))
        story.append(t)
        story.append(Spacer(1, 8))

        # Issue details for problem sites
        probs = [r for r in tier_results if r["issues"]]
        if probs:
            story.append(Paragraph("Issue Details:", styles["SH"]))
            for site in sorted(probs, key=lambda x: x.get("priority", 99)):
                els = [Paragraph(
                    f'<b>{site["label"]}</b> ({site["url"]})', styles["IT"],
                )]
                for typ, msg in site["issues"][:8]:
                    c = {
                        "critical": "#c62828", "warning": "#f57f17", "info": "#1565c0",
                    }.get(typ, "#888")
                    els.append(Paragraph(
                        f'&nbsp;&nbsp;<font color="{c}">[{typ.upper()}]</font> {msg[:85]}',
                        styles["IT"],
                    ))
                els.append(Spacer(1, 4))
                story.append(KeepTogether(els))

    add_tier(results["tier1"], "Tier 1 — High Priority (Deep Audit)")
    story.append(PageBreak())
    add_tier(results["tier2"], "Tier 2 — TLDs + Kill Pages (Standard Audit)")
    story.append(PageBreak())
    add_tier(results["tier3"], "Tier 3 — PPC, SEO & Redirects (Light Audit)")

    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph(
        f"Auto-generated {s['date']} by Weekend QA Bot | "
        f"Scan duration: {s['duration']}s | "
        f"github.com/8amitjain/weekend-qa-bot",
        styles["SM"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf


# ── Slack ────────────────────────────────────────────────────────────────

def post_slack(results, pdf_buf):
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("SLACK_BOT_TOKEN not set — skipping Slack post")
        return False

    s = results["summary"]
    all_r = results["tier1"] + results["tier2"] + results["tier3"]

    # Critical items for message
    crits = []
    for site in sorted(all_r, key=lambda x: x.get("priority", 99)):
        if site["status"] in ("CRITICAL", "DOWN"):
            for t, m in site["issues"]:
                if t == "critical":
                    crits.append(f"  *{site['label']}*: {m[:70]}")
                    break
            else:
                crits.append(f"  *{site['label']}*: Site DOWN")
    crit_text = "\n".join(crits[:12]) if crits else "  None — all clear!"

    # Tier 1 status icons
    t1 = []
    for site in results["tier1"]:
        ico = {
            "PASS": ":white_check_mark:", "WARNING": ":warning:",
            "CRITICAL": ":red_circle:", "DOWN": ":x:",
        }.get(site["status"], ":grey_question:")
        t1.append(f"  {ico} {site['label']}")

    msg = (
        f":mag: *Weekend QA Audit Report — {s['date']}*\n\n"
        f"<@{AMIT_ID}> Here's your automated QA report:\n\n"
        f"*Summary:*\n"
        f"  :bar_chart: Sites Checked: *{s['total']}* (T1: {s['tier_counts']['tier1']}, T2: {s['tier_counts']['tier2']}, T3: {s['tier_counts']['tier3']})\n"
        f"  :red_circle: Critical: *{s['critical']}*\n"
        f"  :warning: Warnings: *{s['warning']}*\n"
        f"  :white_check_mark: Passed: *{s['passed']}*\n"
        f"  :x: Down: *{s['down']}*\n\n"
        f"*Top Critical Issues:*\n{crit_text}\n\n"
        f"*Tier 1 Status:*\n" + "\n".join(t1) + "\n\n"
        f":clock1: Scan: {s['duration']}s | _Automated Saturday 8am EST_"
    )

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Post message
    r = req.post(
        "https://slack.com/api/chat.postMessage",
        headers=hdrs,
        json={"channel": SLACK_CHANNEL, "text": msg, "unfurl_links": False},
    )

    if not (r.status_code == 200 and r.json().get("ok")):
        print(f"Slack message failed: {r.text[:200]}")
        return False
    thread_ts = r.json().get("ts")

    # Upload PDF in thread
    if pdf_buf:
        try:
            pdf_buf.seek(0)
            uh = {"Authorization": f"Bearer {token}"}
            pdf_bytes = pdf_buf.read()
            fname = f"QA_Report_{s['date']}.pdf"

            # Get upload URL
            ur = req.post(
                "https://slack.com/api/files.getUploadURLExternal",
                headers=uh,
                data={"filename": fname, "length": len(pdf_bytes)},
            )
            if ur.status_code == 200 and ur.json().get("ok"):
                upload_url = ur.json()["upload_url"]
                file_id = ur.json()["file_id"]
                # Upload file
                req.post(upload_url, files={"file": (fname, pdf_bytes, "application/pdf")})
                # Complete upload
                req.post(
                    "https://slack.com/api/files.completeUploadExternal",
                    headers=hdrs,
                    json={
                        "files": [{"id": file_id, "title": f"QA Report {s['date']}"}],
                        "channel_id": SLACK_CHANNEL,
                        "thread_ts": thread_ts,
                        "initial_comment": ":page_facing_up: Full PDF report attached.",
                    },
                )
            else:
                print(f"PDF upload failed: {ur.text[:200]}")
        except Exception as e:
            print(f"ERROR uploading PDF to Slack: {traceback.format_exc()}")
        finally:
            # Reset buffer position so callers can still use it (e.g., save locally)
            try:
                pdf_buf.seek(0)
            except Exception:
                pass

    return True


# ── Vercel Handler ───────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Optional: verify cron secret
        cron_secret = os.environ.get("CRON_SECRET")
        if cron_secret:
            auth = self.headers.get("authorization", "")
            if auth != f"Bearer {cron_secret}":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
                return

        try:
            results = run_audit()
            pdf_buf = generate_pdf(results)
            slack_ok = post_slack(results, pdf_buf)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "summary": results["summary"],
                "slack_posted": slack_ok,
            }).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


# ── CLI Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        print(f"Starting Weekend QA Audit... ({len(TIER1)} T1, {len(TIER2)} T2, {len(TIER3)} T3 sites)")
        results = run_audit()

        pdf_buf = generate_pdf(results)
        slack_ok = post_slack(results, pdf_buf)

        # Save PDF locally if OUTPUT_DIR is set
        output_dir = os.environ.get("OUTPUT_DIR")
        if output_dir and pdf_buf is not None:
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d")
            path = os.path.join(output_dir, f"qa-report-{ts}.pdf")
            with open(path, "wb") as f:
                pdf_buf.seek(0)
                f.write(pdf_buf.read())
            print(f"PDF saved to {path}")
        elif output_dir and pdf_buf is None:
            print("WARNING: PDF generation failed, skipping local save.")

        s = results["summary"]
        print(
            f"\nDone! {s['total']} sites checked — "
            f"{s['critical']} critical, {s['warning']} warnings, "
            f"{s['down']} down, {s['passed']} passed. "
            f"Slack posted: {slack_ok}"
        )
    except Exception:
        print("FATAL ERROR in Weekend QA Bot:")
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)
