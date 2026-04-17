"""
Weekend QA Bot — E-Commerce Focused Per-Site PDF Reports via GitHub Actions.
Runs every Saturday at 8am EST (1pm UTC).

Checks all active sites across PharmaxaLabs / Solvaderm / Nuu3:
  E-COMMERCE FOCUS:
  - Cart functionality (add-to-cart buttons, /cart endpoints)
  - Checkout links & flows (buy-now, checkout URLs)
  - Upsell/cross-sell elements (upsell widgets, related products)
  - Pricing display (missing or $0.00 prices)
  - Buy/order buttons & CTAs
  - Shopify cart API health (/cart.js, /cart/add)
  - Payment badge / trust seal presence

  CORE QA (kept):
  - Broken images
  - Broken navigation / internal links
  - SSL certificate health
  - Page load performance
  - Mixed content
  - Placeholder text detection

  REMOVED (skip basic SEO noise):
  - No H1 checks
  - No meta title/description checks
  - No canonical/robots/sitemap checks
  - No Open Graph / schema checks
  - No favicon checks

Generates individual PDF reports per site and posts each to
Slack #automated-qc, tagging @Amit.

Updated: 2026-04-17 — e-commerce focused, skip basic SEO.
"""

import requests as req
import ssl
import socket
import re
import time
import json
import os
import io
import concurrent.futures
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone
from collections import defaultdict

# ── Config ───────────────────────────────────────────────────────────────
TIMEOUT = 12
MAX_WORKERS = 10
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "C0AP3RF4J4B")
AMIT_ID = "D05JGP5EV9R"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
HDRS = {"User-Agent": UA}
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── Product Priority (revenue-ranked from priority sheet) ────────────────
PRODUCT_PRIORITY = {
    "Virectin": 1, "Flexoplex": 2, "Provasil": 3, "Phenocal": 4,
    "Zenotone": 5, "Stemuderm": 6, "Nutesta": 7, "Prostara": 8,
    "Glucoeze": 9, "Menoquil": 10, "Natures Superfuel": 11,
    "Stemnucell": 12, "Vazopril": 13, "Nufolix": 14, "Eyevage": 15,
    "Ocuvital": 16, "ACV Gummies": 17, "Ace Ferulic": 18,
    "Gut Health 365": 19, "Revivatone": 20, "Somulin": 21,
    "Juvabrite": 22, "Serelax": 23, "Colopril": 24,
    "Flexdermal": 25, "Zenofem": 26, "Zenogel": 27,
    "Bonexcin": 28, "Maxolean": 29, "Endmigra": 30,
    "UTM": 31, "Sleep Support": 32, "Liver Health 365": 33,
    "Greenpura": 34,
}

# ── Red-excluded sites (from Google Sheet — marked red) ──────────────────
SKIP = {
    "menoquil.com", "phenocal.com", "provasil.com", "nuu3supergreens.com",
    "completehealthshopping.us", "allwebcoupons.com", "totalbeautyadvisors.com",
    "smarthealthshopping.com", "products.flexoplex.com", "beyondthetalk.net",
    "blog.pharmaxalabs.com", "staging.healthwebmagazine.com",
    "thedailynewsportal.com", "tinnitus.pharmaxalabs.com", "memoforce.online",
    "thierrysanchez.com", "prostastream.online", "themysticwolf.com",
    "besthealthshopping.us", "prostastreamreviews.com",
    "shopping.trustedhealthanswers.com", "totalshoppingdigest.com",
    "newnaturalbook.com", "backup.dailyhealthshopping.com",
    "healthnewsadvisors.com", "shawnboothmeals.com",
    "staging.flexoplexstore.com", "wassupte.com", "5minutehealthfixes.com",
    "supremestrengthforsports.com", "bionoricusa.com",
    "casa-tres-amigos-goa.com", "daxmoypersonaltrainingstudios.com",
    "fromzerotoathlete.com", "journalofinfertility.com",
    "thedietitianchoice.com", "advancedtrochology.com", "jertong.com",
    "kcstrengthcoaching.com", "metropolitantheclub.com", "swissnavylube.com",
}

# ── Active Site List (74 sites, synced from Google Sheets 2026-04-17) ────
# Categories: shopify, tld, kill, solv_kill, nuu3_kill, ppc, seo

SITES = [
    # ── Shopify Main Stores (top-level domains) ──
    {"url": "https://www.virectin.com/", "cat": "shopify", "label": "Virectin Store", "priority": 1},
    {"url": "https://www.flexoplex.com/", "cat": "shopify", "label": "Flexoplex Store", "priority": 2},
    {"url": "https://www.nuu3.com/", "cat": "shopify", "label": "Nuu3 Store", "priority": 11},
    {"url": "https://www.solvadermstore.com/", "cat": "shopify", "label": "Solvaderm Store", "priority": 6},
    {"url": "https://www.pharmaxalabs.com/", "cat": "shopify", "label": "PharmaxaLabs Store", "priority": 1},

    # ── TLD Domains (WordPress official product sites) ──
    {"url": "https://www.serelax.com/", "cat": "tld", "label": "Serelax", "priority": 23},
    {"url": "https://www.somulin.com/", "cat": "tld", "label": "Somulin", "priority": 21},
    {"url": "https://www.prostara.com/", "cat": "tld", "label": "Prostara", "priority": 8},
    {"url": "https://www.colopril.com/", "cat": "tld", "label": "Colopril", "priority": 24},
    {"url": "https://www.flexdermal.com/", "cat": "tld", "label": "Flexdermal", "priority": 25},
    {"url": "https://www.zenofem.com/", "cat": "tld", "label": "Zenofem", "priority": 26},
    {"url": "https://www.zenogel.com/", "cat": "tld", "label": "Zenogel", "priority": 27},
    {"url": "https://www.bonexcin.com/", "cat": "tld", "label": "Bonexcin", "priority": 28},
    {"url": "https://www.glucoeze.com/", "cat": "tld", "label": "Glucoeze", "priority": 9},
    {"url": "https://www.nufolix.com/", "cat": "tld", "label": "Nufolix", "priority": 14},
    {"url": "https://www.nutesta.com/", "cat": "tld", "label": "Nutesta", "priority": 7},
    {"url": "https://www.ocuvital.com/", "cat": "tld", "label": "Ocuvital", "priority": 16},
    {"url": "https://www.zenotone.com/", "cat": "tld", "label": "Zenotone", "priority": 5},
    {"url": "https://www.maxolean.com/", "cat": "tld", "label": "Maxolean", "priority": 29},
    {"url": "https://www.endmigra.com/", "cat": "tld", "label": "Endmigra", "priority": 30},
    {"url": "https://www.greenpura.com/", "cat": "tld", "label": "Greenpura", "priority": 34},
    {"url": "https://www.vazopril.com/", "cat": "tld", "label": "Vazopril", "priority": 13},
    {"url": "https://www.colopril.us/", "cat": "tld", "label": "Colopril US", "priority": 24},
    {"url": "https://www.bonexcin.us/", "cat": "tld", "label": "Bonexcin US", "priority": 28},
    {"url": "https://www.somulin.store/", "cat": "tld", "label": "Somulin Store", "priority": 21},
    {"url": "https://www.myprovasil.com/", "cat": "tld", "label": "MyProvasil", "priority": 3},
    {"url": "https://www.vazoprilstore.com/", "cat": "tld", "label": "Vazopril Store", "priority": 13},
    {"url": "https://www.serelaxstore.com/", "cat": "tld", "label": "Serelax Store", "priority": 23},
    {"url": "https://www.prostarastore.com/", "cat": "tld", "label": "Prostara Store", "priority": 8},
    {"url": "https://www.flexdermalstore.com/", "cat": "tld", "label": "Flexdermal Store", "priority": 25},
    {"url": "https://www.zenofemstore.com/", "cat": "tld", "label": "Zenofem Store", "priority": 26},

    # ── Kill Pages (Google Adwords funnel pages) ──
    {"url": "https://www.virectinstore.com/", "cat": "kill", "label": "Virectin Kill", "priority": 1},
    {"url": "https://www.menoquilstore.com/", "cat": "kill", "label": "Menoquil Kill", "priority": 10},
    {"url": "https://www.flexoplexstore.com/", "cat": "kill", "label": "Flexoplex Kill", "priority": 2},
    {"url": "https://www.provasilstore.com/", "cat": "kill", "label": "Provasil Kill", "priority": 3},
    {"url": "https://www.phenocalstore.com/", "cat": "kill", "label": "Phenocal Kill", "priority": 4},
    {"url": "https://serelax.pharmaxalabs.com/", "cat": "kill", "label": "Serelax Kill Sub", "priority": 23},
    {"url": "https://somulin.pharmaxalabs.com/", "cat": "kill", "label": "Somulin Kill Sub", "priority": 21},
    {"url": "https://prostara.pharmaxalabs.com/", "cat": "kill", "label": "Prostara Kill Sub", "priority": 8},
    {"url": "https://colopril.pharmaxalabs.com/", "cat": "kill", "label": "Colopril Kill Sub", "priority": 24},
    {"url": "https://flexdermal.pharmaxalabs.com/", "cat": "kill", "label": "Flexdermal Kill Sub", "priority": 25},
    {"url": "https://zenofem.pharmaxalabs.com/", "cat": "kill", "label": "Zenofem Kill Sub", "priority": 26},
    {"url": "https://zenogel.pharmaxalabs.com/", "cat": "kill", "label": "Zenogel Kill Sub", "priority": 27},
    {"url": "https://bonexcin.pharmaxalabs.com/", "cat": "kill", "label": "Bonexcin Kill Sub", "priority": 28},
    {"url": "https://menoquil.pharmaxalabs.com/", "cat": "kill", "label": "Menoquil Kill Sub", "priority": 10},
    {"url": "https://zenotone.pharmaxalabs.com/", "cat": "kill", "label": "Zenotone Kill Sub", "priority": 5},
    {"url": "https://glucoeze.pharmaxalabs.com/", "cat": "kill", "label": "Glucoeze Kill Sub", "priority": 9},
    {"url": "https://nufolix.pharmaxalabs.com/", "cat": "kill", "label": "Nufolix Kill Sub", "priority": 14},
    {"url": "https://nutesta.pharmaxalabs.com/", "cat": "kill", "label": "Nutesta Kill Sub", "priority": 7},
    {"url": "https://ocuvital.pharmaxalabs.com/", "cat": "kill", "label": "Ocuvital Kill Sub", "priority": 16},
    {"url": "https://vazopril.pharmaxalabs.com/", "cat": "kill", "label": "Vazopril Kill Sub", "priority": 13},
    {"url": "https://maxolean.pharmaxalabs.com/", "cat": "kill", "label": "Maxolean Kill Sub", "priority": 29},
    {"url": "https://endmigra.pharmaxalabs.com/", "cat": "kill", "label": "Endmigra Kill Sub", "priority": 30},

    # ── Solvaderm Kill Pages ──
    {"url": "https://products.solvadermstore.com/", "cat": "solv_kill", "label": "Solvaderm Products Hub", "priority": 6},
    {"url": "https://products.solvadermstore.com/eyevage/", "cat": "solv_kill", "label": "Eyevage Kill", "priority": 15},
    {"url": "https://products.solvadermstore.com/ace-ferulic/", "cat": "solv_kill", "label": "Ace Ferulic Kill", "priority": 18},
    {"url": "https://products.solvadermstore.com/stemnucell/", "cat": "solv_kill", "label": "Stemnucell Kill", "priority": 12},
    {"url": "https://products.solvadermstore.com/revivatone/", "cat": "solv_kill", "label": "Revivatone Kill", "priority": 20},
    {"url": "https://products.solvadermstore.com/juvabrite/", "cat": "solv_kill", "label": "Juvabrite Kill", "priority": 22},
    {"url": "https://products.solvadermstore.com/universal-tinted-moisturizer/", "cat": "solv_kill", "label": "UTM Kill", "priority": 31},
    {"url": "https://products.solvadermstore.com/stemuderm/", "cat": "solv_kill", "label": "Stemuderm Kill", "priority": 6},

    # ── Nuu3 Kill Pages ──
    {"url": "https://products.nuu3.com/", "cat": "nuu3_kill", "label": "Nuu3 Products Hub", "priority": 11},
    {"url": "https://products.nuu3.com/natures-superfuel/", "cat": "nuu3_kill", "label": "Superfuel Kill", "priority": 11},
    {"url": "https://products.nuu3.com/acv-gummies/", "cat": "nuu3_kill", "label": "ACV Gummies Kill", "priority": 17},
    {"url": "https://products.nuu3.com/gut-health-365/", "cat": "nuu3_kill", "label": "Gut Health Kill", "priority": 19},
    {"url": "https://products.nuu3.com/sleep-support-gummies/", "cat": "nuu3_kill", "label": "Sleep Support Kill", "priority": 32},
    {"url": "https://products.nuu3.com/liver-health-365/", "cat": "nuu3_kill", "label": "Liver Health Kill", "priority": 33},

    # ── PPC Sites (PBN for Google Adwords) ──
    {"url": "https://www.totalhealthreports.us/", "cat": "ppc", "label": "Total Health Reports", "priority": 50},
    {"url": "https://blog.totalhealthreports.us/", "cat": "ppc", "label": "THR Blog", "priority": 50},
    {"url": "https://news.totalhealthreports.us/", "cat": "ppc", "label": "THR News", "priority": 50},
    {"url": "https://www.dailyhealthshopping.com/", "cat": "ppc", "label": "Daily Health Shopping", "priority": 50},
    {"url": "https://www.trustedhealthanswers.com/", "cat": "ppc", "label": "Trusted Health Answers", "priority": 50},

    # ── SEO Sites (PBN SEO) ──
    {"url": "https://www.healthwebmagazine.com/", "cat": "seo", "label": "Health Web Magazine", "priority": 60},
    {"url": "https://www.skinformulations.com/", "cat": "seo", "label": "Skin Formulations", "priority": 60},
]


# ── Check Functions ──────────────────────────────────────────────────────

def check_http(url):
    """HTTP status, response time, and HTML content."""
    try:
        start = time.time()
        r = req.get(url, headers=HDRS, timeout=TIMEOUT, allow_redirects=True)
        elapsed = round(time.time() - start, 2)
        return {
            "code": r.status_code,
            "time": elapsed,
            "ok": r.status_code == 200,
            "html": r.text,
            "final_url": r.url,
            "redirected": r.url != url,
            "content_type": r.headers.get("Content-Type", ""),
        }
    except req.exceptions.SSLError as e:
        return {"code": None, "err": f"SSL error: {str(e)[:100]}", "ok": False, "html": ""}
    except req.exceptions.ConnectionError as e:
        return {"code": None, "err": f"Connection failed: {str(e)[:100]}", "ok": False, "html": ""}
    except req.exceptions.Timeout:
        return {"code": None, "err": f"Timeout — no response in {TIMEOUT}s", "ok": False, "html": ""}
    except Exception as e:
        return {"code": None, "err": str(e)[:100], "ok": False, "html": ""}


def check_ssl(url):
    """SSL certificate validity and expiry."""
    hostname = urlparse(url).hostname
    if not hostname:
        return {"ok": False, "err": "Bad hostname"}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as s:
            with ctx.wrap_socket(s, server_hostname=hostname) as ss:
                cert = ss.getpeercert()
                days = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400
                return {"ok": True, "days": round(days), "warn": days < 30}
    except Exception as e:
        return {"ok": False, "err": str(e)[:80]}


def check_images(html, base_url):
    """Find broken images — checks actual image URLs return 200."""
    issues = []
    parsed = urlparse(base_url)

    # Find all <img src="...">
    img_tags = re.findall(r'<img\s+[^>]*?src=["\']([^"\']+)["\'][^>]*?>', html, re.I)

    # Also find CSS background images
    bg_imgs = re.findall(r'background(?:-image)?\s*:\s*url\(["\']?([^"\')\s]+)["\']?\)', html, re.I)

    all_imgs = list(set(img_tags + bg_imgs))

    # Filter out data URIs, SVG inline, tracking pixels
    real_imgs = []
    for img in all_imgs:
        if img.startswith("data:"):
            continue
        if img.startswith("{{") or img.startswith("{%"):
            continue  # template tags
        if len(img) < 5:
            continue
        # Resolve relative URLs
        if img.startswith("//"):
            img = f"{parsed.scheme}:{img}"
        elif img.startswith("/"):
            img = f"{parsed.scheme}://{parsed.netloc}{img}"
        elif not img.startswith("http"):
            img = urljoin(base_url, img)
        real_imgs.append(img)

    # Check up to 20 images
    broken = []
    for img_url in real_imgs[:20]:
        try:
            r = req.head(img_url, headers=HDRS, timeout=5, allow_redirects=True)
            if r.status_code >= 400:
                broken.append(img_url)
        except Exception:
            broken.append(img_url)

    # Images without alt text
    no_alt_tags = re.findall(r'<img\s+[^>]*?>', html, re.I)
    no_alt = [t for t in no_alt_tags if 'alt=' not in t.lower() or re.search(r'alt=["\'][\s]*["\']', t, re.I)]

    if broken:
        issues.append(("critical", f"{len(broken)} broken image(s)", broken[:5]))
    if no_alt:
        total_imgs = len(no_alt_tags)
        issues.append(("warning", f"{len(no_alt)}/{total_imgs} images missing or empty alt text", []))

    return issues, len(real_imgs)


def check_navigation(html, base_url):
    """Check nav links for broken pages."""
    issues = []
    parsed = urlparse(base_url)

    # Find links inside <nav>, <header>, or elements with nav-related classes
    nav_html = ""
    nav_blocks = re.findall(
        r'<(?:nav|header)[^>]*>.*?</(?:nav|header)>',
        html, re.I | re.S
    )
    nav_html = " ".join(nav_blocks)

    # Also grab links in common nav class patterns
    nav_class_blocks = re.findall(
        r'<[^>]+class=["\'][^"\']*(?:nav|menu|header|topbar)[^"\']*["\'][^>]*>.*?</(?:div|ul|section)>',
        html, re.I | re.S
    )
    nav_html += " ".join(nav_class_blocks)

    if not nav_html:
        # Fallback: check first 50 links on page
        nav_html = html

    links = re.findall(r'href=["\']([^"\'#]+)["\']', nav_html, re.I)

    # Resolve and deduplicate
    resolved = set()
    for link in links:
        if link.startswith("mailto:") or link.startswith("tel:") or link.startswith("javascript:"):
            continue
        if link.startswith("/"):
            resolved.add(f"{parsed.scheme}://{parsed.netloc}{link}")
        elif parsed.netloc in link:
            resolved.add(link)

    # Check up to 15 nav links
    nav_links = list(resolved)[:15]
    broken = []
    for link in nav_links:
        try:
            r = req.head(link, headers=HDRS, timeout=6, allow_redirects=True)
            if r.status_code >= 400:
                broken.append(f"{link} ({r.status_code})")
        except Exception:
            broken.append(f"{link} (timeout)")

    if broken:
        issues.append(("critical", f"{len(broken)} broken navigation link(s)", broken[:5]))

    if not nav_blocks:
        issues.append(("warning", "No <nav> or <header> element found", []))

    return issues, len(nav_links)


def check_meta(html, url):
    """Minimal meta checks — only critical issues, skip basic SEO noise."""
    issues = []

    # Viewport (critical for mobile purchases)
    if not re.search(r'<meta\s+name=["\']viewport["\']', html, re.I):
        issues.append(("critical", "Missing viewport meta (not mobile-friendly — kills mobile conversions)", []))

    # Mixed content (breaks trust for checkout)
    if url.startswith("https"):
        mc = re.findall(r'(?:src|href)=["\']http://(?!localhost)', html, re.I)
        if mc:
            issues.append(("warning", f"Mixed content: {len(mc)} HTTP resources on HTTPS page (triggers browser warnings)", []))

    # Placeholder text
    if "lorem ipsum" in html.lower():
        issues.append(("critical", "Lorem Ipsum placeholder text found on page", []))
    if re.search(r"coming\s+soon", html, re.I) and "<title" in html.lower():
        issues.append(("warning", "'Coming soon' text detected", []))

    # Robots noindex on a sales page is critical
    robots = re.search(r'<meta\s+name=["\']robots["\']\s+content=["\']([^"\']*)["\']', html, re.I)
    if robots and "noindex" in robots.group(1).lower():
        issues.append(("warning", "Page is set to noindex — Google won't index this page", []))

    return issues


def check_ecommerce(html, url):
    """E-commerce functionality checks: cart, checkout, upsell, pricing, buy buttons."""
    issues = []
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    html_lower = html.lower()

    # ── 1. Add-to-Cart Buttons ──
    atc_patterns = [
        r'add[\s_-]?to[\s_-]?cart', r'addtocart', r'add-to-cart',
        r'btn[\s_-]?cart', r'cart[\s_-]?btn', r'product[\s_-]?form',
        r'shopify-payment-button', r'data-action=["\']add[\s_-]?to[\s_-]?cart',
    ]
    has_atc = any(re.search(p, html_lower) for p in atc_patterns)

    # Check for buy/order buttons
    buy_patterns = [
        r'buy[\s_-]?now', r'order[\s_-]?now', r'purchase[\s_-]?now',
        r'shop[\s_-]?now', r'get[\s_-]?yours', r'claim[\s_-]?yours',
        r'try[\s_-]?it[\s_-]?now', r'start[\s_-]?your[\s_-]?order',
        r'buy[\s_-]?(?:1|2|3|one|two|three)', r'select[\s_-]?package',
        r'choose[\s_-]?package', r'select[\s_-]?quantity',
    ]
    has_buy = any(re.search(p, html_lower) for p in buy_patterns)

    if not has_atc and not has_buy:
        issues.append(("critical", "No add-to-cart or buy/order button found — users cannot purchase", []))
    elif not has_atc:
        issues.append(("info", "No add-to-cart button (has buy/order button)", []))

    # ── 2. Checkout Links ──
    checkout_patterns = [
        r'href=["\'][^"\']*checkout[^"\']*["\']',
        r'href=["\'][^"\']*\/cart[^"\']*["\']',
        r'action=["\'][^"\']*checkout[^"\']*["\']',
        r'action=["\'][^"\']*\/cart[^"\']*["\']',
    ]
    has_checkout_link = any(re.search(p, html_lower) for p in checkout_patterns)

    # Check for Shopify checkout-specific patterns
    shopify_checkout = re.findall(
        r'href=["\']([^"\']*(?:checkout|myshopify\.com/cart|/cart)[^"\']*)["\']',
        html, re.I
    )

    # Check if checkout URLs are actually reachable
    broken_checkout = []
    for ck_url in shopify_checkout[:5]:
        if ck_url.startswith("/"):
            ck_url = f"{base}{ck_url}"
        elif not ck_url.startswith("http"):
            ck_url = urljoin(url, ck_url)
        try:
            r = req.head(ck_url, headers=HDRS, timeout=6, allow_redirects=True)
            if r.status_code >= 400:
                broken_checkout.append(f"{ck_url} ({r.status_code})")
        except Exception:
            broken_checkout.append(f"{ck_url} (timeout)")

    if broken_checkout:
        issues.append(("critical", f"{len(broken_checkout)} broken checkout/cart link(s)", broken_checkout[:3]))

    # ── 3. Pricing Display ──
    price_patterns = [
        r'\$\d+[\.,]\d{2}',  # $XX.XX
        r'class=["\'][^"\']*price[^"\']*["\']',
        r'data-price',
        r'class=["\'][^"\']*product-price[^"\']*["\']',
        r'itemprop=["\']price["\']',
    ]
    has_price = any(re.search(p, html_lower) for p in price_patterns)

    # Check for $0.00 or empty prices
    zero_prices = re.findall(r'\$0\.00', html)
    if zero_prices:
        issues.append(("critical", f"$0.00 price found ({len(zero_prices)} occurrences) — likely pricing error", []))

    if not has_price and (has_atc or has_buy):
        issues.append(("warning", "Buy/order button present but no visible pricing found on page", []))

    # ── 4. Upsell / Cross-Sell Elements ──
    upsell_patterns = [
        r'upsell', r'cross[\s_-]?sell', r'you[\s_-]?may[\s_-]?also[\s_-]?like',
        r'related[\s_-]?products?', r'frequently[\s_-]?bought',
        r'customers[\s_-]?also[\s_-]?(?:bought|viewed)',
        r'recommended[\s_-]?(?:products?|for[\s_-]?you)',
        r'add[\s_-]?(?:this|these)[\s_-]?(?:too|also)',
        r'bundle[\s_-]?(?:deal|save|offer)',
        r'best[\s_-]?(?:seller|value)[\s_-]?(?:pack|bundle)',
        r'save[\s_-]?(?:more|\d+%)',
        r'(?:2|3|4|5|6)[\s_-]?(?:pack|bottle|month)',
        r'most[\s_-]?popular[\s_-]?(?:pack|choice)',
    ]
    has_upsell = any(re.search(p, html_lower) for p in upsell_patterns)

    # Upsell link validation — check if upsell links work
    upsell_links = re.findall(
        r'<(?:a|button)[^>]*(?:upsell|cross-sell|recommended|bundle)[^>]*href=["\']([^"\']+)["\']',
        html, re.I
    )
    broken_upsell = []
    for u_url in upsell_links[:5]:
        if u_url.startswith("/"):
            u_url = f"{base}{u_url}"
        elif not u_url.startswith("http"):
            u_url = urljoin(url, u_url)
        try:
            r = req.head(u_url, headers=HDRS, timeout=6, allow_redirects=True)
            if r.status_code >= 400:
                broken_upsell.append(f"{u_url} ({r.status_code})")
        except Exception:
            broken_upsell.append(f"{u_url} (timeout)")

    if broken_upsell:
        issues.append(("critical", f"{len(broken_upsell)} broken upsell/cross-sell link(s)", broken_upsell[:3]))

    # ── 5. Shopify Cart API Health ──
    # Only for Shopify sites (check for Shopify indicators)
    is_shopify = any(x in html_lower for x in [
        'shopify', 'cdn.shopify.com', 'myshopify.com', 'shopify-section',
    ])

    if is_shopify:
        # Check /cart.js endpoint
        try:
            r = req.get(f"{base}/cart.js", headers=HDRS, timeout=6)
            if r.status_code != 200:
                issues.append(("critical", f"Shopify /cart.js returns {r.status_code} — cart may be broken", []))
            else:
                try:
                    cart_data = r.json()
                    # cart_data should have 'items', 'total_price', etc.
                    if "items" not in cart_data and "item_count" not in cart_data:
                        issues.append(("warning", "Shopify /cart.js response missing expected fields", []))
                except Exception:
                    issues.append(("warning", "Shopify /cart.js returned non-JSON response", []))
        except Exception:
            issues.append(("warning", "Shopify /cart.js unreachable", []))

        # Check /collections exists
        try:
            r = req.head(f"{base}/collections", headers=HDRS, timeout=6, allow_redirects=True)
            if r.status_code >= 400:
                issues.append(("info", f"Shopify /collections returns {r.status_code}", []))
        except Exception:
            pass

    # ── 6. Payment / Trust Badges ──
    trust_patterns = [
        r'(?:visa|mastercard|amex|paypal|apple[\s_-]?pay|google[\s_-]?pay|shop[\s_-]?pay)',
        r'(?:secure[\s_-]?checkout|ssl[\s_-]?secure|money[\s_-]?back[\s_-]?guarantee)',
        r'(?:trust[\s_-]?badge|trust[\s_-]?seal|mcafee|norton|truste)',
        r'(?:satisfaction[\s_-]?guarantee|100%[\s_-]?secure)',
    ]
    has_trust = any(re.search(p, html_lower) for p in trust_patterns)
    if not has_trust and (has_atc or has_buy):
        issues.append(("warning", "No payment badges or trust seals found — may reduce checkout confidence", []))

    # ── 7. Form/CTA Validation ──
    # Check if product forms have valid action URLs
    form_actions = re.findall(r'<form[^>]*action=["\']([^"\']+)["\'][^>]*>', html, re.I)
    for action_url in form_actions:
        if any(kw in action_url.lower() for kw in ['cart', 'checkout', 'order', 'purchase']):
            if action_url.startswith("/"):
                full_url = f"{base}{action_url}"
            elif action_url.startswith("http"):
                full_url = action_url
            else:
                full_url = urljoin(url, action_url)
            try:
                r = req.head(full_url, headers=HDRS, timeout=6, allow_redirects=True)
                if r.status_code >= 400:
                    issues.append(("critical", f"Cart/checkout form action returns {r.status_code}", [full_url]))
            except Exception:
                issues.append(("warning", f"Cart/checkout form action unreachable", [full_url]))

    # ── 8. Quantity Selector ──
    qty_patterns = [
        r'type=["\']number["\'][^>]*(?:quantity|qty)',
        r'(?:quantity|qty)[^>]*type=["\']number["\']',
        r'name=["\'](?:quantity|qty)["\']',
        r'class=["\'][^"\']*(?:quantity|qty)[^"\']*["\']',
        r'data-quantity',
    ]
    has_qty = any(re.search(p, html_lower) for p in qty_patterns)
    if has_atc and not has_qty:
        issues.append(("info", "Add-to-cart present but no quantity selector found", []))

    return issues, {
        "has_atc": has_atc,
        "has_buy": has_buy,
        "has_checkout_link": has_checkout_link,
        "has_price": has_price,
        "has_upsell": has_upsell,
        "has_trust": has_trust,
        "is_shopify": is_shopify,
        "has_qty": has_qty,
    }


def check_performance(http_result, html):
    """Basic performance checks."""
    issues = []
    resp_time = http_result.get("time", 0)

    if resp_time > 8:
        issues.append(("critical", f"Very slow page load: {resp_time}s", []))
    elif resp_time > 5:
        issues.append(("warning", f"Slow page load: {resp_time}s (target <3s)", []))
    elif resp_time > 3:
        issues.append(("info", f"Moderate load time: {resp_time}s", []))

    # HTML size
    if html:
        kb = len(html) / 1024
        if kb > 1000:
            issues.append(("warning", f"Very large HTML: {round(kb)}KB (target <500KB)", []))
        elif kb > 500:
            issues.append(("info", f"Large HTML: {round(kb)}KB", []))

    return issues


# check_resources removed — skip robots.txt/sitemap.xml (basic SEO noise)


# ── Per-Site Audit ───────────────────────────────────────────────────────

def audit_site(site):
    """Run all core QA checks for a single site. Returns a result dict."""
    url = site["url"]
    result = {
        "url": url,
        "label": site["label"],
        "cat": site["cat"],
        "priority": site.get("priority", 99),
        "checks": {},
        "issues": [],
        "status": "UNKNOWN",
        "resp_time": None,
        "images_checked": 0,
        "nav_links_checked": 0,
        "ecom": {},
    }

    # 1. HTTP check
    http = check_http(url)
    result["checks"]["http"] = {
        "code": http.get("code"),
        "time": http.get("time"),
        "ok": http["ok"],
    }

    if not http["ok"]:
        result["issues"].append(("critical", http.get("err", f"HTTP {http.get('code')}"), []))
        result["status"] = "DOWN"
        result["resp_time"] = http.get("time")
        result["counts"] = {"critical": 1, "warning": 0, "info": 0}
        return result

    result["resp_time"] = http.get("time")
    html = http.get("html", "")

    # 2. SSL check
    ssl_result = check_ssl(url)
    result["checks"]["ssl"] = ssl_result
    if not ssl_result["ok"]:
        result["issues"].append(("critical", f"SSL error: {ssl_result.get('err', 'failed')}", []))
    elif ssl_result.get("warn"):
        result["issues"].append(("critical", f"SSL certificate expires in {ssl_result['days']} days!", []))
    elif ssl_result.get("days") and ssl_result["days"] < 60:
        result["issues"].append(("warning", f"SSL expires in {ssl_result['days']} days", []))

    if html:
        # 3. Broken images
        img_issues, img_count = check_images(html, url)
        result["issues"].extend(img_issues)
        result["images_checked"] = img_count

        # 4. Navigation / broken links
        nav_issues, nav_count = check_navigation(html, url)
        result["issues"].extend(nav_issues)
        result["nav_links_checked"] = nav_count

        # 5. Minimal meta checks (viewport, mixed content, placeholder — skip SEO)
        result["issues"].extend(check_meta(html, url))

        # 6. E-COMMERCE CHECKS (cart, checkout, upsell, pricing, buy buttons)
        ecom_issues, ecom_flags = check_ecommerce(html, url)
        result["issues"].extend(ecom_issues)
        result["ecom"] = ecom_flags

        # 7. Performance
        result["issues"].extend(check_performance(http, html))

    # Determine status
    crits = sum(1 for t, _, _ in result["issues"] if t == "critical")
    warns = sum(1 for t, _, _ in result["issues"] if t == "warning")
    result["status"] = "CRITICAL" if crits else ("WARNING" if warns else "PASS")
    result["counts"] = {"critical": crits, "warning": warns,
                        "info": sum(1 for t, _, _ in result["issues"] if t == "info")}
    return result


# ── PDF Generation (per site) ───────────────────────────────────────────

def generate_site_pdf(result):
    """Generate a PDF report for a single site."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle("Title2", parent=styles["Title"], fontSize=22,
        textColor=HexColor("#1a1a2e"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11,
        textColor=HexColor("#666"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("SH", parent=styles["Heading2"], fontSize=14,
        textColor=HexColor("#1a1a2e"), spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle("Issue", parent=styles["Normal"], fontSize=9.5,
        leading=13, spaceBefore=2, spaceAfter=2, leftIndent=12))
    styles.add(ParagraphStyle("Detail", parent=styles["Normal"], fontSize=8.5,
        leading=11, textColor=HexColor("#555"), leftIndent=24))
    styles.add(ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7.5,
        textColor=HexColor("#999"), alignment=TA_CENTER))

    story = []

    # ── Header ──
    status_color = {"CRITICAL": "#c62828", "WARNING": "#f57f17", "PASS": "#2e7d32",
                    "DOWN": "#b71c1c"}.get(result["status"], "#888")

    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph("QA Audit Report", styles["Title2"]))
    story.append(Paragraph(result["label"], styles["Sub"]))
    story.append(Paragraph(
        f'<font color="#888">{result["url"]}</font>', styles["Sub"]))
    story.append(Paragraph(
        f'<font color="{status_color}" size="14"><b>{result["status"]}</b></font>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;{TODAY}', styles["Sub"]))
    story.append(Spacer(1, 0.2 * inch))

    # ── Summary Stats ──
    counts = result.get("counts", {})
    stat_data = [[
        Paragraph(f'<font size="16" color="#c62828"><b>{counts.get("critical", 0)}</b></font>', styles["Sub"]),
        Paragraph(f'<font size="16" color="#f57f17"><b>{counts.get("warning", 0)}</b></font>', styles["Sub"]),
        Paragraph(f'<font size="16" color="#1565c0"><b>{counts.get("info", 0)}</b></font>', styles["Sub"]),
        Paragraph(f'<font size="16"><b>{result.get("resp_time", "N/A")}s</b></font>', styles["Sub"]),
    ], [
        Paragraph("Critical", styles["Footer"]),
        Paragraph("Warnings", styles["Footer"]),
        Paragraph("Info", styles["Footer"]),
        Paragraph("Load Time", styles["Footer"]),
    ]]
    st = Table(stat_data, colWidths=[1.5 * inch] * 4)
    st.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, HexColor("#e0e0e0")),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    story.append(st)
    story.append(Spacer(1, 0.15 * inch))

    cat_names = {"shopify": "Shopify Store", "tld": "TLD (WordPress)",
                 "kill": "Kill Page", "solv_kill": "Solvaderm Kill Page",
                 "nuu3_kill": "Nuu3 Kill Page", "ppc": "PPC Site", "seo": "SEO Site"}
    story.append(Paragraph(
        f'<font color="#888">Category: {cat_names.get(result["cat"], result["cat"])}'
        f' &nbsp;|&nbsp; Images checked: {result["images_checked"]}'
        f' &nbsp;|&nbsp; Nav links checked: {result["nav_links_checked"]}</font>',
        styles["Footer"]))
    story.append(Spacer(1, 0.15 * inch))

    # ── E-Commerce Status Bar ──
    ecom = result.get("ecom", {})
    if ecom:
        def _flag(val, label):
            c = "#2e7d32" if val else "#c62828"
            icon = "YES" if val else "NO"
            return f'<font color="{c}" size="8"><b>{icon}</b></font> <font size="7" color="#666">{label}</font>'

        ecom_items = [
            _flag(ecom.get("has_atc"), "Cart"),
            _flag(ecom.get("has_buy"), "Buy Btn"),
            _flag(ecom.get("has_checkout_link"), "Checkout"),
            _flag(ecom.get("has_price"), "Pricing"),
            _flag(ecom.get("has_upsell"), "Upsell"),
            _flag(ecom.get("has_trust"), "Trust"),
        ]
        ecom_row = [[Paragraph(item, styles["Footer"]) for item in ecom_items]]
        et = Table(ecom_row, colWidths=[1.0 * inch] * 6)
        et.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f8f8f8")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#e0e0e0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(Paragraph(
            '<font color="#1a1a2e" size="10"><b>E-Commerce Status</b></font>',
            styles["Sub"]))
        story.append(Spacer(1, 0.05 * inch))
        story.append(et)

    story.append(Spacer(1, 0.2 * inch))

    # ── Issues by Severity ──
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_issues = sorted(result["issues"], key=lambda x: severity_order.get(x[0], 3))

    if not sorted_issues:
        story.append(Paragraph("All Checks Passed", styles["SH"]))
        story.append(Paragraph(
            '<font color="#2e7d32">No issues found. Site is healthy.</font>',
            styles["Issue"]))
    else:
        # Group by severity
        for sev, sev_label, sev_color in [
            ("critical", "Critical Issues", "#c62828"),
            ("warning", "Warnings", "#f57f17"),
            ("info", "Informational", "#1565c0"),
        ]:
            sev_issues = [i for i in sorted_issues if i[0] == sev]
            if not sev_issues:
                continue

            story.append(Paragraph(
                f'<font color="{sev_color}">{sev_label} ({len(sev_issues)})</font>',
                styles["SH"]))

            for typ, msg, details in sev_issues:
                icon = {"critical": "X", "warning": "!", "info": "i"}.get(typ, "?")
                els = [Paragraph(
                    f'<font color="{sev_color}"><b>[{icon}]</b></font> {msg}',
                    styles["Issue"])]
                # Show detail URLs (broken images/links)
                for detail in details[:3]:
                    short = detail if len(detail) < 80 else detail[:77] + "..."
                    els.append(Paragraph(
                        f'<font color="#888">&rarr; {short}</font>',
                        styles["Detail"]))
                story.append(KeepTogether(els))

    # ── Footer ──
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph(
        f"Generated {TODAY} by Weekend QA Bot | github.com/8amitjain/weekend-qa-bot",
        styles["Footer"]))

    doc.build(story)
    buf.seek(0)
    return buf


# ── Summary PDF (overview of all sites) ──────────────────────────────────

def generate_summary_pdf(all_results):
    """Generate a single summary PDF with an overview table of all sites."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("CT", parent=styles["Title"], fontSize=24,
        textColor=HexColor("#1a1a2e"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("CS", parent=styles["Normal"], fontSize=12,
        textColor=HexColor("#666"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("SH", parent=styles["Heading2"], fontSize=14,
        textColor=HexColor("#1a1a2e"), spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle("SM", parent=styles["Normal"], fontSize=8,
        textColor=HexColor("#888")))
    styles.add(ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10))

    story = []
    total = len(all_results)
    crits = sum(1 for r in all_results if r["status"] == "CRITICAL")
    warns = sum(1 for r in all_results if r["status"] == "WARNING")
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    down = sum(1 for r in all_results if r["status"] == "DOWN")

    # Cover
    story.append(Spacer(1, 1 * inch))
    story.append(Paragraph("Weekend QA Audit Summary", styles["CT"]))
    story.append(Paragraph(f"{TODAY} | {total} Sites", styles["CS"]))
    story.append(Paragraph("PharmaxaLabs / Solvaderm / Nuu3", styles["CS"]))
    story.append(Spacer(1, 0.3 * inch))

    stat_data = [[
        Paragraph(f'<font size="20">{total}</font>', styles["CS"]),
        Paragraph(f'<font size="20" color="#c62828">{crits}</font>', styles["CS"]),
        Paragraph(f'<font size="20" color="#f57f17">{warns}</font>', styles["CS"]),
        Paragraph(f'<font size="20" color="#2e7d32">{passed}</font>', styles["CS"]),
        Paragraph(f'<font size="20" color="#b71c1c">{down}</font>', styles["CS"]),
    ], [
        Paragraph("Total", styles["SM"]),
        Paragraph("Critical", styles["SM"]),
        Paragraph("Warnings", styles["SM"]),
        Paragraph("Passed", styles["SM"]),
        Paragraph("Down", styles["SM"]),
    ]]
    st = Table(stat_data, colWidths=[1.2 * inch] * 5)
    st.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, HexColor("#e0e0e0")),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    story.append(st)
    story.append(PageBreak())

    # Sites table by category
    cat_order = ["shopify", "tld", "kill", "solv_kill", "nuu3_kill", "ppc", "seo"]
    cat_names = {"shopify": "Shopify Stores", "tld": "TLD Domains",
                 "kill": "Kill Pages", "solv_kill": "Solvaderm Kill Pages",
                 "nuu3_kill": "Nuu3 Kill Pages", "ppc": "PPC Sites", "seo": "SEO Sites"}

    for cat in cat_order:
        cat_results = sorted(
            [r for r in all_results if r["cat"] == cat],
            key=lambda x: x.get("priority", 99))
        if not cat_results:
            continue

        story.append(Paragraph(cat_names.get(cat, cat), styles["SH"]))
        rows = [["Site", "Status", "Load", "Crit", "Cart", "Checkout", "Upsell"]]
        for r in cat_results:
            sc = {"CRITICAL": "#c62828", "WARNING": "#f57f17",
                  "PASS": "#2e7d32", "DOWN": "#b71c1c"}.get(r["status"], "#888")
            c = r.get("counts", {})
            ecom = r.get("ecom", {})
            def _yn(val):
                if val:
                    return '<font size="7" color="#2e7d32">OK</font>'
                return '<font size="7" color="#c62828">NO</font>'
            rows.append([
                Paragraph(f'<font size="8">{r["label"]}</font>', styles["Cell"]),
                Paragraph(f'<font size="8" color="{sc}"><b>{r["status"]}</b></font>', styles["Cell"]),
                Paragraph(f'<font size="8">{r.get("resp_time", "N/A")}s</font>', styles["Cell"]),
                Paragraph(f'<font size="8">{c.get("critical", 0)}</font>', styles["Cell"]),
                Paragraph(_yn(ecom.get("has_atc") or ecom.get("has_buy")), styles["Cell"]),
                Paragraph(_yn(ecom.get("has_checkout_link")), styles["Cell"]),
                Paragraph(_yn(ecom.get("has_upsell")), styles["Cell"]),
            ])
        t = Table(rows, colWidths=[2.0 * inch, 0.7 * inch, 0.55 * inch, 0.45 * inch, 0.55 * inch, 0.7 * inch, 0.55 * inch],
                  repeatRows=1)
        ts = [
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e0e0e0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i in range(2, len(rows), 2):
            ts.append(("BACKGROUND", (0, i), (-1, i), HexColor("#f5f5f5")))
        t.setStyle(TableStyle(ts))
        story.append(t)
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        f"Generated {TODAY} by Weekend QA Bot | github.com/8amitjain/weekend-qa-bot",
        styles["SM"]))
    doc.build(story)
    buf.seek(0)
    return buf


# ── Slack Helpers ───────────────────────────────────────────────────────


def _check_slack_scopes(token):
    """Check if the Slack bot token has the required scopes for file uploads."""
    try:
        r = req.post("https://slack.com/api/auth.test",
                     headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200 and r.json().get("ok"):
            # The response headers contain the scopes
            scopes = r.headers.get("x-oauth-scopes", "")
            print(f"Slack bot scopes: {scopes}")
            has_files = "files:write" in scopes or "files:read" in scopes
            if not has_files:
                print("WARNING: Bot token is missing 'files:write' scope — PDF uploads will fail!")
                print("  → Go to https://api.slack.com/apps → your app → OAuth & Permissions")
                print("  → Add scopes: files:write, files:read → Reinstall the app")
            return has_files
        else:
            print(f"Slack auth.test failed: {r.json().get('error', 'unknown')}")
            return False
    except Exception as e:
        print(f"Slack scope check error: {e}")
        return False


def _upload_pdf(token, hdrs, pdf_buf, filename, title, channel, thread_ts, comment):
    """Upload a PDF to Slack using the new files.upload API. Returns True on success."""
    uh = {"Authorization": f"Bearer {token}"}
    pdf_buf.seek(0)
    pdf_bytes = pdf_buf.read()

    if len(pdf_bytes) == 0:
        print(f"  SKIP {filename}: PDF buffer is empty")
        return False

    print(f"  Uploading {filename} ({len(pdf_bytes)} bytes)...")

    try:
        # Step 1: Get upload URL
        ur = req.post("https://slack.com/api/files.getUploadURLExternal",
                      headers=uh, data={"filename": filename, "length": len(pdf_bytes)})
        ur_data = ur.json()
        if not (ur.status_code == 200 and ur_data.get("ok")):
            err = ur_data.get("error", ur.text[:200])
            print(f"  FAIL Step 1 getUploadURL for {filename}: {err}")
            if "missing_scope" in str(err) or "not_allowed" in str(err):
                print("  → Bot token needs 'files:write' scope. Add it in Slack App settings.")
            return False

        upload_url = ur_data["upload_url"]
        file_id = ur_data["file_id"]
        print(f"  Step 1 OK — got upload URL and file_id={file_id}")

        # Step 2: Upload file content
        up_resp = req.post(upload_url, files={"file": (filename, pdf_bytes, "application/pdf")})
        if up_resp.status_code not in (200, 201):
            print(f"  FAIL Step 2 upload content for {filename}: HTTP {up_resp.status_code} — {up_resp.text[:200]}")
            return False
        print(f"  Step 2 OK — file content uploaded")

        # Step 3: Complete upload and share to channel/thread
        comp = req.post("https://slack.com/api/files.completeUploadExternal", headers=hdrs,
                        json={
                            "files": [{"id": file_id, "title": title}],
                            "channel_id": channel,
                            "thread_ts": thread_ts,
                            "initial_comment": comment,
                        })
        comp_data = comp.json()
        if not comp_data.get("ok"):
            err = comp_data.get("error", "unknown")
            print(f"  FAIL Step 3 completeUpload for {filename}: {err}")
            if "not_in_channel" in str(err):
                print("  → Bot needs to be invited to the channel: /invite @YourBotName")
            elif "channel_not_found" in str(err):
                print(f"  → Channel {channel} not found or bot doesn't have access")
            return False

        print(f"  OK uploaded {filename} to Slack")
        return True

    except Exception as e:
        print(f"  ERROR uploading {filename}: {e}")
        import traceback
        traceback.print_exc()
        return False


def _post_text_fallback(hdrs, channel, thread_ts, result):
    """Post a text summary of site issues as fallback when PDF upload fails."""
    issues_text = []
    for sev, msg, _ in result["issues"][:10]:
        icon = ":red_circle:" if sev == "critical" else ":warning:" if sev == "warning" else ":information_source:"
        issues_text.append(f"  {icon} {msg[:100]}")

    text = (
        f":page_facing_up: *{result['label']}* [{result['status']}] — "
        f"{result['counts'].get('critical', 0)} critical, "
        f"{result['counts'].get('warning', 0)} warnings\n"
        + "\n".join(issues_text)
    )
    if len(result["issues"]) > 10:
        text += f"\n  _...and {len(result['issues']) - 10} more issues_"

    try:
        req.post("https://slack.com/api/chat.postMessage", headers=hdrs,
                 json={"channel": channel, "text": text,
                        "thread_ts": thread_ts, "unfurl_links": False})
    except Exception as e:
        print(f"  Text fallback also failed for {result['label']}: {e}")


# ── Slack Posting ────────────────────────────────────────────────────────

def post_to_slack(all_results, site_pdfs, summary_pdf):
    """Post summary message + per-site PDFs to Slack."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("SLACK_BOT_TOKEN not set — skipping Slack")
        return False

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Check if we have file upload permissions
    can_upload = _check_slack_scopes(token)
    total = len(all_results)
    crits = sum(1 for r in all_results if r["status"] == "CRITICAL")
    warns = sum(1 for r in all_results if r["status"] == "WARNING")
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    down = sum(1 for r in all_results if r["status"] == "DOWN")

    # Build critical items list — focus on ecommerce issues
    crit_lines = []
    for r in sorted(all_results, key=lambda x: x.get("priority", 99)):
        if r["status"] in ("CRITICAL", "DOWN"):
            # Prioritize ecommerce issues in the summary
            ecom_issues = [m for t, m, _ in r["issues"] if t == "critical" and
                          any(kw in m.lower() for kw in ["cart", "checkout", "buy", "order", "price", "upsell", "purchase"])]
            top_issue = ecom_issues[0] if ecom_issues else next((m for t, m, _ in r["issues"] if t == "critical"), "Site down")
            crit_lines.append(f"  :red_circle: *{r['label']}*: {top_issue[:70]}")

    crit_text = "\n".join(crit_lines[:15]) if crit_lines else "  :white_check_mark: None — all clear!"

    # Count ecommerce-specific issues
    ecom_broken = sum(1 for r in all_results
        if any("cart" in m.lower() or "checkout" in m.lower() or "buy" in m.lower()
               or "purchase" in m.lower() for t, m, _ in r["issues"] if t == "critical"))

    msg = (
        f":shopping_trolley: *Weekend E-Commerce QA Audit — {TODAY}*\n\n"
        f"<@{AMIT_ID}> Here's your automated QA report:\n\n"
        f"*Summary ({total} sites):*\n"
        f"  :red_circle: Critical: *{crits}* &nbsp;|&nbsp; "
        f":warning: Warnings: *{warns}* &nbsp;|&nbsp; "
        f":white_check_mark: Passed: *{passed}* &nbsp;|&nbsp; "
        f":x: Down: *{down}*\n"
        f"  :shopping_trolley: Cart/Checkout issues: *{ecom_broken}*\n\n"
        f"*Top E-Commerce Issues:*\n{crit_text}\n\n"
        f"_Individual PDF reports for each site are in the thread below._\n"
        f":clock1: _Automated Saturday 8am EST — E-Commerce Focus_"
    )

    # Post summary message
    r = req.post("https://slack.com/api/chat.postMessage", headers=hdrs,
                 json={"channel": SLACK_CHANNEL, "text": msg, "unfurl_links": False})

    if not (r.status_code == 200 and r.json().get("ok")):
        print(f"Slack message failed: {r.text[:300]}")
        return False

    thread_ts = r.json().get("ts")

    # Upload summary PDF in thread
    if can_upload:
        summary_ok = _upload_pdf(token, hdrs, summary_pdf, f"QA_Summary_{TODAY}.pdf",
                    f"QA Summary {TODAY}", SLACK_CHANNEL, thread_ts,
                    ":bar_chart: Full summary report (all sites)")
        if not summary_ok:
            print("Summary PDF upload failed — but will still try per-site PDFs individually")
    else:
        print("WARNING: No files:write scope — all PDFs will use text fallback")
        print("  → Go to https://api.slack.com/apps → your app → OAuth & Permissions")
        print("  → Add scopes: files:write, files:read → Reinstall the app")

    # Upload per-site PDFs — only for sites with issues
    problem_sites = [(r, pdf) for r, pdf in site_pdfs if r["status"] != "PASS"]
    problem_sites.sort(key=lambda x: x[0].get("priority", 99))

    pdf_success = 0
    pdf_fail = 0
    for result, pdf_buf in problem_sites:
        safe_label = re.sub(r'[^a-zA-Z0-9_-]', '_', result["label"])
        fname = f"QA_{safe_label}_{TODAY}.pdf"
        title = f"{result['label']} — {result['status']}"
        comment = (
            f":page_facing_up: *{result['label']}* [{result['status']}] — "
            f"{result['counts'].get('critical', 0)} critical, "
            f"{result['counts'].get('warning', 0)} warnings"
        )
        if can_upload:
            ok = _upload_pdf(token, hdrs, pdf_buf, fname, title, SLACK_CHANNEL, thread_ts, comment)
            if ok:
                pdf_success += 1
            else:
                # PDF upload failed for THIS site — post text fallback
                _post_text_fallback(hdrs, SLACK_CHANNEL, thread_ts, result)
                pdf_fail += 1
        else:
            # No file upload permission — always use text fallback
            _post_text_fallback(hdrs, SLACK_CHANNEL, thread_ts, result)
            pdf_fail += 1
        time.sleep(1.0)  # Slack rate limit — 1s between file uploads

    print(f"  PDF uploads: {pdf_success} OK, {pdf_fail} failed (text fallback used)")

    # Post a pass-list summary in thread
    pass_sites = [r for r in all_results if r["status"] == "PASS"]
    if pass_sites:
        pass_msg = ":white_check_mark: *Sites that passed all checks:*\n"
        for r in sorted(pass_sites, key=lambda x: x.get("priority", 99)):
            pass_msg += f"  - {r['label']} ({r.get('resp_time', '?')}s)\n"
        req.post("https://slack.com/api/chat.postMessage", headers=hdrs,
                 json={"channel": SLACK_CHANNEL, "text": pass_msg,
                        "thread_ts": thread_ts, "unfurl_links": False})

    return True


# ── Main Runner ──────────────────────────────────────────────────────────

def run_audit():
    """Run QA audit on all active sites (excluding red/skip list)."""
    print(f"Starting audit on {len(SITES)} sites (skipping {len(SKIP)} red sites)...")

    # Filter out skipped sites
    active = []
    for site in SITES:
        host = urlparse(site["url"]).netloc.replace("www.", "")
        if host not in SKIP:
            active.append(site)
        else:
            print(f"  Skipping (red): {site['label']} ({host})")

    print(f"Auditing {len(active)} active sites...")

    # Run audits in parallel
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {ex.submit(audit_site, s): s for s in active}
        for future in concurrent.futures.as_completed(future_map):
            try:
                result = future.result()
                results.append(result)
                status_icon = {"CRITICAL": "X", "WARNING": "!", "PASS": ".", "DOWN": "D"}.get(result["status"], "?")
                print(f"  [{status_icon}] {result['label']}: {result['status']}")
            except Exception as e:
                site = future_map[future]
                print(f"  [E] {site['label']}: {e}")
                results.append({
                    "url": site["url"], "label": site["label"], "cat": site["cat"],
                    "priority": site.get("priority", 99), "issues": [("critical", f"Audit error: {e}", [])],
                    "status": "DOWN", "counts": {"critical": 1, "warning": 0, "info": 0},
                    "resp_time": None, "images_checked": 0, "nav_links_checked": 0,
                })

    return results


def main():
    start = time.time()
    results = run_audit()

    # Generate per-site PDFs
    print(f"\nGenerating {len(results)} per-site PDF reports...")
    site_pdfs = []
    for r in results:
        try:
            pdf = generate_site_pdf(r)
            site_pdfs.append((r, pdf))
        except Exception as e:
            print(f"  PDF error for {r['label']}: {e}")

    # Generate summary PDF
    print("Generating summary PDF...")
    summary_pdf = generate_summary_pdf(results)

    # Save PDFs locally if OUTPUT_DIR set
    output_dir = os.environ.get("OUTPUT_DIR")
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        # Save summary
        with open(os.path.join(output_dir, f"QA_Summary_{TODAY}.pdf"), "wb") as f:
            summary_pdf.seek(0)
            f.write(summary_pdf.read())
        # Save per-site
        for r, pdf in site_pdfs:
            safe = re.sub(r'[^a-zA-Z0-9_-]', '_', r["label"])
            with open(os.path.join(output_dir, f"QA_{safe}_{TODAY}.pdf"), "wb") as f:
                pdf.seek(0)
                f.write(pdf.read())
        print(f"PDFs saved to {output_dir}/")

    # Post to Slack
    print("Posting to Slack...")
    slack_ok = post_to_slack(results, site_pdfs, summary_pdf)

    duration = round(time.time() - start)
    total = len(results)
    crits = sum(1 for r in results if r["status"] == "CRITICAL")
    warns = sum(1 for r in results if r["status"] == "WARNING")
    down = sum(1 for r in results if r["status"] == "DOWN")
    passed = sum(1 for r in results if r["status"] == "PASS")

    print(
        f"\nDone in {duration}s! {total} sites — "
        f"{crits} critical, {warns} warnings, {down} down, {passed} passed. "
        f"Slack: {'OK' if slack_ok else 'FAILED'}"
    )
    return results


# ── Vercel Handler (kept for backwards compat) ──────────────────────────

try:
    from http.server import BaseHTTPRequestHandler

    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
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
                results = main()
                total = len(results)
                crits = sum(1 for r in results if r["status"] == "CRITICAL")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True, "total": total, "critical": crits,
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
except ImportError:
    pass


# ── CLI Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
