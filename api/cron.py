"""
Weekend QA Bot v2 — Playwright-Powered E-Commerce Auditor
Runs every Saturday at 8am EST (1pm UTC) via GitHub Actions.

Uses a real headless browser (Playwright/Chromium) to:
  - Render pages fully with JavaScript
  - Find and click buy/add-to-cart buttons
  - Verify cart actually updates after click
  - Detect JavaScript errors
  - Catch broken images via network monitoring
  - Take screenshots for visual review
  - Check for placeholder text, $0.00 prices, rendering bugs

Keeps lightweight checks from requests:
  - SSL certificate health
  - HTTP status / redirects
  - Page load performance

Report: compact PDF (only sites with issues), screenshots in Slack thread.

Updated: 2026-05-15 — v2 rewrite with Playwright, replaces regex-on-raw-HTML approach.
"""

import asyncio
import requests as req
import ssl
import socket
import re
import time
import json
import os
import io
from urllib.parse import urlparse
from datetime import datetime, timezone
from playwright.async_api import async_playwright

# ── Config ───────────────────────────────────────────────────────────────
NAV_TIMEOUT = 25000      # 25s page load timeout
RENDER_WAIT = 2500       # 2.5s extra wait for JS rendering
CART_WAIT = 3500         # 3.5s wait after clicking buy button
CONCURRENCY = 4          # parallel browser contexts
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "C0AP3RF4J4B")
AMIT_ID = "U05K6HRC4V6"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

# ── Active Site List ─────────────────────────────────────────────────────
SITES = [
    # Shopify Main Stores
    {"url": "https://www.virectin.com/", "cat": "shopify", "label": "Virectin Store", "priority": 1},
    {"url": "https://www.flexoplex.com/", "cat": "shopify", "label": "Flexoplex Store", "priority": 2},
    {"url": "https://www.nuu3.com/", "cat": "shopify", "label": "Nuu3 Store", "priority": 11},
    {"url": "https://www.solvadermstore.com/", "cat": "shopify", "label": "Solvaderm Store", "priority": 6},
    {"url": "https://www.pharmaxalabs.com/", "cat": "shopify", "label": "PharmaxaLabs Store", "priority": 1},

    # TLD Domains (WordPress product sites)
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

    # Kill Pages (Google Adwords funnel pages)
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

    # Solvaderm Kill Pages
    {"url": "https://products.solvadermstore.com/", "cat": "solv_kill", "label": "Solvaderm Products Hub", "priority": 6},
    {"url": "https://products.solvadermstore.com/eyevage/", "cat": "solv_kill", "label": "Eyevage Kill", "priority": 15},
    {"url": "https://products.solvadermstore.com/ace-ferulic/", "cat": "solv_kill", "label": "Ace Ferulic Kill", "priority": 18},
    {"url": "https://products.solvadermstore.com/stemnucell/", "cat": "solv_kill", "label": "Stemnucell Kill", "priority": 12},
    {"url": "https://products.solvadermstore.com/revivatone/", "cat": "solv_kill", "label": "Revivatone Kill", "priority": 20},
    {"url": "https://products.solvadermstore.com/juvabrite/", "cat": "solv_kill", "label": "Juvabrite Kill", "priority": 22},
    {"url": "https://products.solvadermstore.com/universal-tinted-moisturizer/", "cat": "solv_kill", "label": "UTM Kill", "priority": 31},
    {"url": "https://products.solvadermstore.com/stemuderm/", "cat": "solv_kill", "label": "Stemuderm Kill", "priority": 6},

    # Nuu3 Kill Pages
    {"url": "https://products.nuu3.com/", "cat": "nuu3_kill", "label": "Nuu3 Products Hub", "priority": 11},
    {"url": "https://products.nuu3.com/natures-superfuel/", "cat": "nuu3_kill", "label": "Superfuel Kill", "priority": 11},
    {"url": "https://products.nuu3.com/acv-gummies/", "cat": "nuu3_kill", "label": "ACV Gummies Kill", "priority": 17},
    {"url": "https://products.nuu3.com/gut-health-365/", "cat": "nuu3_kill", "label": "Gut Health Kill", "priority": 19},
    {"url": "https://products.nuu3.com/sleep-support-gummies/", "cat": "nuu3_kill", "label": "Sleep Support Kill", "priority": 32},
    {"url": "https://products.nuu3.com/liver-health-365/", "cat": "nuu3_kill", "label": "Liver Health Kill", "priority": 33},

    # PPC Sites
    {"url": "https://www.totalhealthreports.us/", "cat": "ppc", "label": "Total Health Reports", "priority": 50},
    {"url": "https://blog.totalhealthreports.us/", "cat": "ppc", "label": "THR Blog", "priority": 50},
    {"url": "https://news.totalhealthreports.us/", "cat": "ppc", "label": "THR News", "priority": 50},
    {"url": "https://www.dailyhealthshopping.com/", "cat": "ppc", "label": "Daily Health Shopping", "priority": 50},
    {"url": "https://www.trustedhealthanswers.com/", "cat": "ppc", "label": "Trusted Health Answers", "priority": 50},

    # SEO Sites
    {"url": "https://www.healthwebmagazine.com/", "cat": "seo", "label": "Health Web Magazine", "priority": 60},
    {"url": "https://www.skinformulations.com/", "cat": "seo", "label": "Skin Formulations", "priority": 60},
]

# Categories that are product/store pages (need e-commerce checks)
ECOM_CATS = {"shopify", "kill", "solv_kill", "nuu3_kill", "tld"}

# Buy/CTA button selectors (Playwright locator syntax)
BUY_SELECTORS = [
    'button:visible:has-text("Add to Cart")',
    'button:visible:has-text("Add To Cart")',
    'button:visible:has-text("Buy Now")',
    'button:visible:has-text("Buy It Now")',
    'button:visible:has-text("Order Now")',
    'button:visible:has-text("Shop Now")',
    'a:visible:has-text("Add to Cart")',
    'a:visible:has-text("Buy Now")',
    'a:visible:has-text("Order Now")',
    'a:visible:has-text("Get Yours")',
    'a:visible:has-text("Claim Yours")',
    'a:visible:has-text("Try It Now")',
    'a:visible:has-text("Select Package")',
    'a:visible:has-text("Choose Package")',
    'a:visible:has-text("Select Your Package")',
    '.shopify-payment-button button:visible',
    'form[action="/cart/add"] button[type="submit"]:visible',
    'button.add-to-cart:visible',
    '[data-action="add-to-cart"]:visible',
]


# ── SSL Check (lightweight, uses requests) ───────────────────────────────

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


# ── Playwright Site Audit ────────────────────────────────────────────────

async def _find_buy_button(page):
    """Find a visible buy/add-to-cart/order button on the current page."""
    for sel in BUY_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return loc
        except Exception:
            continue
    return None


async def _test_cart_flow(page, buy_button, base_url):
    """Click the buy button and verify the cart actually updates."""
    issues = []
    try:
        await buy_button.click()
        await page.wait_for_timeout(CART_WAIT)

        # Check 1: Did we navigate to /cart or /checkout?
        if "/cart" in page.url or "/checkout" in page.url:
            return issues  # Cart flow works

        # Check 2: Did a cart drawer/modal appear?
        cart_drawer_sels = [
            ".cart-drawer:visible", ".cart-modal:visible",
            "[data-cart-drawer]:visible", ".mini-cart:visible",
            ".cart-notification:visible", ".side-cart:visible",
            "[class*='cart'][class*='drawer']:visible",
            "[class*='cart'][class*='modal']:visible",
        ]
        for sel in cart_drawer_sels:
            try:
                if await page.locator(sel).first.count() > 0:
                    return issues  # Cart drawer appeared
            except Exception:
                continue

        # Check 3: Shopify /cart.js — did item_count increase?
        try:
            cart_data = await page.evaluate("""
                async () => {
                    try {
                        const r = await fetch('/cart.js');
                        return await r.json();
                    } catch { return null; }
                }
            """)
            if cart_data and cart_data.get("item_count", 0) > 0:
                return issues  # Cart has items
        except Exception:
            pass

        # None of the checks passed — cart flow seems broken
        issues.append(("critical", "Add-to-cart clicked but cart did not update — checkout flow may be broken"))

    except Exception as e:
        issues.append(("warning", f"Cart flow test error: {str(e)[:80]}"))

    return issues


async def audit_site(browser, site):
    """Full Playwright-based audit of a single site."""
    url = site["url"]
    cat = site["cat"]

    result = {
        "url": url,
        "label": site["label"],
        "cat": cat,
        "priority": site.get("priority", 99),
        "issues": [],          # list of (severity, message) tuples
        "screenshot": None,    # PNG bytes
        "load_time": None,
    }

    # ── 1. SSL check ──
    ssl_info = check_ssl(url)
    if not ssl_info["ok"]:
        result["issues"].append(("critical", f"SSL error: {ssl_info.get('err', 'unknown')}"))
    elif ssl_info.get("warn"):
        result["issues"].append(("critical", f"SSL certificate expires in {ssl_info['days']} days — renew immediately"))

    # ── 2. Browser checks ──
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=UA,
        ignore_https_errors=True,
    )
    page = await context.new_page()

    # Collect JS errors and failed network requests
    js_errors = []
    failed_resources = []

    def _on_console(msg):
        if msg.type == "error":
            js_errors.append(msg.text)

    def _on_request_failed(request):
        failed_resources.append({
            "url": request.url,
            "type": request.resource_type,
        })

    page.on("console", _on_console)
    page.on("requestfailed", _on_request_failed)

    try:
        start = time.time()
        resp = await page.goto(url, wait_until="load", timeout=NAV_TIMEOUT)
        await page.wait_for_timeout(RENDER_WAIT)  # Let JS render
        result["load_time"] = round(time.time() - start, 2)

        # HTTP status check
        if resp is None:
            result["issues"].append(("critical", "Page returned no response"))
            await context.close()
            return result

        if resp.status >= 400:
            result["issues"].append(("critical", f"Page returned HTTP {resp.status}"))
            result["screenshot"] = await page.screenshot(type="png")
            await context.close()
            return result

        # Screenshot (viewport only, not full page — keeps it manageable)
        result["screenshot"] = await page.screenshot(type="png")

        # Get visible page text for content checks
        try:
            body_text = await page.inner_text("body")
        except Exception:
            body_text = ""

        # ── E-Commerce Checks (product/store pages only) ──
        if cat in ECOM_CATS:
            buy_button = await _find_buy_button(page)

            if not buy_button:
                # For Shopify main stores, try navigating to a product page first
                if cat == "shopify":
                    product_sels = [
                        'a[href*="/products/"]:visible',
                        '.product-card a:visible',
                        '.product-grid a:visible',
                        '.collection-product a:visible',
                    ]
                    for sel in product_sels:
                        try:
                            loc = page.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click()
                                await page.wait_for_load_state("load")
                                await page.wait_for_timeout(RENDER_WAIT)
                                buy_button = await _find_buy_button(page)
                                # Update screenshot to show product page
                                result["screenshot"] = await page.screenshot(type="png")
                                break
                        except Exception:
                            continue

            if not buy_button:
                result["issues"].append(("critical",
                    "No visible buy/add-to-cart button found — customers cannot purchase"))

            # Cart flow test (Shopify stores + kill pages with Shopify backend)
            if buy_button and cat in ("shopify", "solv_kill", "nuu3_kill"):
                cart_issues = await _test_cart_flow(page, buy_button, url)
                result["issues"].extend(cart_issues)

            # Pricing check
            if "$0.00" in body_text:
                result["issues"].append(("critical",
                    "$0.00 price displayed on page — likely pricing configuration error"))

        # ── Universal Checks ──

        # Broken images (from network monitoring)
        broken_imgs = [r for r in failed_resources if r["type"] == "image"]
        if broken_imgs:
            urls = [r["url"].split("?")[0].split("/")[-1] for r in broken_imgs[:3]]
            result["issues"].append(("warning",
                f"{len(broken_imgs)} broken image(s): {', '.join(urls)}"))

        # JavaScript errors (filter noise — only real errors)
        critical_js = [e for e in js_errors if any(kw in e.lower() for kw in [
            "cannot read", "is not defined", "is not a function",
            "typeerror", "referenceerror", "syntaxerror",
            "failed to fetch", "network error", "uncaught",
        ])]
        if critical_js:
            first = critical_js[0][:100]
            result["issues"].append(("warning",
                f"{len(critical_js)} JS error(s) — {first}"))

        # Placeholder / broken text
        if "lorem ipsum" in body_text.lower():
            result["issues"].append(("critical",
                "Lorem Ipsum placeholder text found on page"))

        # Visible rendering bugs ("undefined", "null", "NaN" repeated)
        for bad_text in ["undefined", "null", "NaN"]:
            count = body_text.count(bad_text)
            if count >= 3:
                result["issues"].append(("warning",
                    f"'{bad_text}' appears {count} times on page — likely JavaScript rendering bug"))
                break

        # Coming soon on live page
        if re.search(r"coming\s+soon", body_text, re.I):
            result["issues"].append(("warning", "'Coming soon' text detected on live page"))

        # Performance
        if result["load_time"] and result["load_time"] > 8:
            result["issues"].append(("warning",
                f"Very slow page load: {result['load_time']}s"))
        elif result["load_time"] and result["load_time"] > 5:
            result["issues"].append(("info",
                f"Slow page load: {result['load_time']}s (target <3s)"))

    except Exception as e:
        err = str(e)[:120]
        if "timeout" in err.lower():
            result["issues"].append(("critical",
                f"Page did not load within {NAV_TIMEOUT // 1000}s — site may be down"))
        else:
            result["issues"].append(("critical", f"Page failed to load: {err}"))
    finally:
        await context.close()

    return result


# ── PDF Report (compact — only problem sites) ───────────────────────────

def generate_report_pdf(all_results):
    """Generate a compact PDF: only sites with issues, plain text format."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, KeepTogether, HRFlowable, Image
    )
    from PIL import Image as PILImage

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Title2", parent=styles["Title"], fontSize=22,
        textColor=HexColor("#1a1a2e"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11,
        textColor=HexColor("#666"), alignment=TA_CENTER, spaceAfter=6))
    styles.add(ParagraphStyle("SiteName", parent=styles["Heading3"], fontSize=12,
        textColor=HexColor("#1a1a2e"), spaceBefore=14, spaceAfter=2))
    styles.add(ParagraphStyle("SiteURL", parent=styles["Normal"], fontSize=8,
        textColor=HexColor("#888"), spaceAfter=4))
    styles.add(ParagraphStyle("IssueLine", parent=styles["Normal"], fontSize=9.5,
        leading=13, leftIndent=12, spaceBefore=1, spaceAfter=1, wordWrap='CJK'))
    styles.add(ParagraphStyle("PassedList", parent=styles["Normal"], fontSize=9,
        textColor=HexColor("#2e7d32"), leading=12, spaceBefore=1))
    styles.add(ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7.5,
        textColor=HexColor("#999"), alignment=TA_CENTER))

    story = []
    total = len(all_results)
    problem_results = [r for r in all_results if r["issues"]]
    passed_count = total - len(problem_results)

    sev_colors = {"critical": "#c62828", "warning": "#e65100", "info": "#1565c0"}
    sev_labels = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO"}

    # ── Header ──
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Weekend QA Report", styles["Title2"]))
    story.append(Paragraph(
        f"{TODAY} &nbsp;|&nbsp; {total} sites audited &nbsp;|&nbsp; "
        f'<font color="#c62828">{len(problem_results)} with issues</font> &nbsp;|&nbsp; '
        f'<font color="#2e7d32">{passed_count} passed</font>',
        styles["Sub"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e0e0e0")))
    story.append(Spacer(1, 0.1 * inch))

    if not problem_results:
        story.append(Spacer(1, 0.5 * inch))
        story.append(Paragraph(
            '<font color="#2e7d32" size="16"><b>All sites passed.</b></font>',
            styles["Sub"]))
        story.append(Paragraph("No issues detected across any of the audited sites.", styles["Sub"]))
    else:
        # ── Problem Sites ──
        for result in sorted(problem_results, key=lambda r: r.get("priority", 99)):
            site_els = []

            # Site header
            site_els.append(Paragraph(result["label"], styles["SiteName"]))
            site_els.append(Paragraph(result["url"], styles["SiteURL"]))

            # Issues — one line each
            for sev, msg in result["issues"]:
                color = sev_colors.get(sev, "#888")
                label = sev_labels.get(sev, "INFO")
                site_els.append(Paragraph(
                    f'<font color="{color}"><b>[{label}]</b></font> {msg}',
                    styles["IssueLine"]))

            # Add screenshot thumbnail if available
            if result.get("screenshot"):
                try:
                    img = PILImage.open(io.BytesIO(result["screenshot"]))
                    img.thumbnail((360, 225))
                    img_buf = io.BytesIO()
                    img.save(img_buf, format="PNG")
                    img_buf.seek(0)
                    site_els.append(Spacer(1, 4))
                    site_els.append(Image(img_buf, width=360, height=225))
                except Exception:
                    pass  # Skip screenshot if processing fails

            site_els.append(Spacer(1, 6))

            # Keep site header + first issues together
            story.append(KeepTogether(site_els[:5]))
            for el in site_els[5:]:
                story.append(el)

    # ── Passed Sites (one-liner, skip if none) ──
    passed_sites = [r for r in all_results if not r["issues"]]
    if passed_sites:
        story.append(Spacer(1, 0.15 * inch))
        story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e0e0e0")))
        story.append(Spacer(1, 0.1 * inch))
        names = ", ".join(r["label"] for r in sorted(passed_sites, key=lambda r: r.get("priority", 99)))
        story.append(Paragraph(
            f'<font color="#2e7d32"><b>Passed ({len(passed_sites)}):</b></font> {names}',
            styles["PassedList"]))

    # Footer
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        f"Generated {TODAY} by Weekend QA Bot v2 (Playwright) | github.com/8amitjain/weekend-qa-bot",
        styles["Footer"]))

    doc.build(story)
    buf.seek(0)
    return buf


# ── Slack Helpers ────────────────────────────────────────────────────────

def _check_slack_scopes(token):
    """Check if the Slack bot token has the required scopes."""
    try:
        r = req.post("https://slack.com/api/auth.test",
                     headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200 and r.json().get("ok"):
            scopes = r.headers.get("x-oauth-scopes", "")
            has_files = "files:write" in scopes
            if not has_files:
                print("WARNING: Bot missing 'files:write' scope — PDF uploads will fail")
            return has_files
        return False
    except Exception:
        return False


def _upload_pdf(token, hdrs, pdf_buf, filename, title, channel, thread_ts, comment):
    """Upload a PDF to Slack using the files.upload API."""
    uh = {"Authorization": f"Bearer {token}"}
    pdf_buf.seek(0)
    pdf_bytes = pdf_buf.read()
    if not pdf_bytes:
        return False

    try:
        ur = req.post("https://slack.com/api/files.getUploadURLExternal",
                      headers=uh, data={"filename": filename, "length": len(pdf_bytes)})
        ur_data = ur.json()
        if not ur_data.get("ok"):
            print(f"  Upload URL failed: {ur_data.get('error')}")
            return False

        req.post(ur_data["upload_url"],
                 files={"file": (filename, pdf_bytes, "application/pdf")})

        comp = req.post("https://slack.com/api/files.completeUploadExternal", headers=hdrs,
                        json={"files": [{"id": ur_data["file_id"], "title": title}],
                              "channel_id": channel, "thread_ts": thread_ts,
                              "initial_comment": comment})
        return comp.json().get("ok", False)
    except Exception as e:
        print(f"  Upload error: {e}")
        return False


def _upload_screenshot(token, hdrs, img_bytes, filename, channel, thread_ts, comment):
    """Upload a screenshot image to Slack thread."""
    uh = {"Authorization": f"Bearer {token}"}
    try:
        ur = req.post("https://slack.com/api/files.getUploadURLExternal",
                      headers=uh, data={"filename": filename, "length": len(img_bytes)})
        ur_data = ur.json()
        if not ur_data.get("ok"):
            return False

        req.post(ur_data["upload_url"],
                 files={"file": (filename, img_bytes, "image/png")})

        comp = req.post("https://slack.com/api/files.completeUploadExternal", headers=hdrs,
                        json={"files": [{"id": ur_data["file_id"], "title": filename}],
                              "channel_id": channel, "thread_ts": thread_ts,
                              "initial_comment": comment})
        return comp.json().get("ok", False)
    except Exception:
        return False


# ── Slack Posting ────────────────────────────────────────────────────────

def post_to_slack(all_results, report_pdf):
    """Post summary + PDF + screenshots to Slack."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("SLACK_BOT_TOKEN not set — skipping Slack")
        return False

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    can_upload = _check_slack_scopes(token)

    total = len(all_results)
    problem_results = [r for r in all_results if r["issues"]]
    passed_count = total - len(problem_results)

    # Count critical vs warning
    crit_sites = sum(1 for r in problem_results
                     if any(s == "critical" for s, _ in r["issues"]))

    # Build concise summary
    if not problem_results:
        status_line = f"All {total} sites passed with no issues."
    else:
        issue_lines = []
        for r in sorted(problem_results, key=lambda x: x.get("priority", 99))[:10]:
            top_issue = next((m for s, m in r["issues"] if s == "critical"),
                            next((m for s, m in r["issues"]), ""))
            issue_lines.append(f"  *{r['label']}*: {top_issue[:70]}")
        status_line = "\n".join(issue_lines)

    msg = (
        f"*Weekend QA Report — {TODAY}*\n\n"
        f"<@{AMIT_ID}> Audit complete.\n\n"
        f"*{total}* sites audited — "
        f"*{len(problem_results)}* with issues, "
        f"*{passed_count}* passed\n\n"
        f"*Sites with issues:*\n{status_line}\n\n"
        f"_Full report (PDF) and screenshots in thread below._"
    )

    r = req.post("https://slack.com/api/chat.postMessage", headers=hdrs,
                 json={"channel": SLACK_CHANNEL, "text": msg, "unfurl_links": False})

    if not (r.status_code == 200 and r.json().get("ok")):
        print(f"Slack message failed: {r.text[:300]}")
        return False

    thread_ts = r.json().get("ts")

    # Upload PDF
    if can_upload and report_pdf:
        _upload_pdf(token, hdrs, report_pdf,
                    f"QA_Report_{TODAY}.pdf", f"QA Report {TODAY}",
                    SLACK_CHANNEL, thread_ts,
                    f"Full report — {len(problem_results)} sites with issues")

        # Upload screenshots for problem sites
        for result in sorted(problem_results, key=lambda x: x.get("priority", 99)):
            if result.get("screenshot"):
                safe = re.sub(r'[^a-zA-Z0-9_-]', '_', result["label"])
                _upload_screenshot(token, hdrs, result["screenshot"],
                    f"{safe}_{TODAY}.png", SLACK_CHANNEL, thread_ts,
                    f"Screenshot: *{result['label']}*")
                time.sleep(0.8)  # Rate limit

    return True


# ── Main Runner ──────────────────────────────────────────────────────────

async def run_audit():
    """Run Playwright-based audit on all active sites."""
    active = []
    for site in SITES:
        host = urlparse(site["url"]).netloc.replace("www.", "")
        if host not in SKIP:
            active.append(site)
        else:
            print(f"  Skipping (red): {site['label']}")

    print(f"Auditing {len(active)} sites with Playwright...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def audit_with_limit(site):
            async with semaphore:
                try:
                    result = await audit_site(browser, site)
                    status = "ISSUE" if result["issues"] else "PASS"
                    icon = "!" if status == "ISSUE" else "."
                    print(f"  [{icon}] {result['label']}: {status} ({result.get('load_time', '?')}s)")
                    return result
                except Exception as e:
                    print(f"  [E] {site['label']}: {e}")
                    return {
                        "url": site["url"], "label": site["label"],
                        "cat": site["cat"], "priority": site.get("priority", 99),
                        "issues": [("critical", f"Audit error: {str(e)[:100]}")],
                        "screenshot": None, "load_time": None,
                    }

        results = await asyncio.gather(*[audit_with_limit(s) for s in active])
        await browser.close()

    return list(results)


def main():
    start = time.time()
    results = asyncio.run(run_audit())

    # Generate compact PDF
    print(f"\nGenerating report PDF...")
    try:
        report_pdf = generate_report_pdf(results)
    except Exception as e:
        print(f"  PDF error: {e}")
        import traceback
        traceback.print_exc()
        report_pdf = None

    # Save locally if OUTPUT_DIR set
    output_dir = os.environ.get("OUTPUT_DIR")
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        if report_pdf:
            with open(os.path.join(output_dir, f"QA_Report_{TODAY}.pdf"), "wb") as f:
                report_pdf.seek(0)
                f.write(report_pdf.read())
        # Save screenshots
        for r in results:
            if r.get("screenshot") and r["issues"]:
                safe = re.sub(r'[^a-zA-Z0-9_-]', '_', r["label"])
                with open(os.path.join(output_dir, f"{safe}_{TODAY}.png"), "wb") as f:
                    f.write(r["screenshot"])
        print(f"  Saved to {output_dir}/")

    # Post to Slack
    if report_pdf:
        print("Posting to Slack...")
        slack_ok = post_to_slack(results, report_pdf)
    else:
        slack_ok = False

    duration = round(time.time() - start)
    total = len(results)
    problems = sum(1 for r in results if r["issues"])
    passed = total - problems

    print(f"\nDone in {duration}s! {total} sites — {problems} with issues, {passed} passed. "
          f"Slack: {'OK' if slack_ok else 'FAILED'}")
    return results


# ── Vercel Handler (backwards compat) ────────────────────────────────────

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
                problems = sum(1 for r in results if r["issues"])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True, "total": total, "issues": problems,
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
except ImportError:
    pass


if __name__ == "__main__":
    main()
