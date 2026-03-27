"""
Weekend QA Audit — Vercel Cron Serverless Function.
Runs every Saturday at 8am EST (1pm UTC).
Checks all active sites, generates PDF, posts to Slack.
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
import concurrent.futures
from urllib.parse import urlparse
from datetime import datetime, timezone

# ── Config ───────────────────────────────────────────────────────────────

TIMEOUT = 8
MAX_WORKERS = 15
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "C0AP3RF4J4B")
AMIT_ID = "D05JGP5EV9R"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
HDRS = {"User-Agent": UA}

# ── Site Lists ───────────────────────────────────────────────────────────

TIER1 = [
    {"url": "https://www.solvadermstore.com/", "cat": "shopify", "label": "Solvaderm Store"},
    {"url": "https://www.flexoplex.com/", "cat": "shopify", "label": "Flexoplex Store"},
    {"url": "https://www.virectin.com/", "cat": "shopify", "label": "Virectin Store"},
    {"url": "https://www.nuu3.com/", "cat": "shopify", "label": "Nuu3 Store"},
    {"url": "https://www.pharmaxalabs.com/", "cat": "shopify", "label": "PharmaxaLabs Store"},
    {"url": "https://www.zenotone.com/", "cat": "tld", "label": "Zenotone (#5)"},
    {"url": "https://www.nutesta.com/", "cat": "tld", "label": "Nutesta (#7)"},
    {"url": "https://www.prostara.com/", "cat": "tld", "label": "Prostara (#8)"},
    {"url": "https://www.glucoeze.com/", "cat": "tld", "label": "Glucoeze (#9)"},
    {"url": "https://www.virectinstore.com/", "cat": "kill", "label": "Virectin Kill (#1)"},
    {"url": "https://www.flexoplexstore.com/", "cat": "kill", "label": "Flexoplex Kill (#2)"},
    {"url": "https://products.solvadermstore.com/stemuderm/", "cat": "kill", "label": "Stemuderm Kill (#6)"},
    {"url": "https://products.solvadermstore.com/eyevage/", "cat": "kill", "label": "Eyevage Kill (#15)"},
]

TIER2 = [
    {"url": "https://www.serelax.com/", "cat": "tld", "label": "Serelax"},
    {"url": "https://www.somulin.com/", "cat": "tld", "label": "Somulin"},
    {"url": "https://www.colopril.com/", "cat": "tld", "label": "Colopril"},
    {"url": "https://www.flexdermal.com/", "cat": "tld", "label": "Flexdermal"},
    {"url": "https://www.zenofem.com/", "cat": "tld", "label": "Zenofem"},
    {"url": "https://www.zenogel.com/", "cat": "tld", "label": "Zenogel"},
    {"url": "https://www.bonexcin.com/", "cat": "tld", "label": "Bonexcin"},
    {"url": "https://www.nufolix.com/", "cat": "tld", "label": "Nufolix"},
    {"url": "https://www.ocuvital.com/", "cat": "tld", "label": "Ocuvital"},
    {"url": "https://www.maxolean.com/", "cat": "tld", "label": "Maxolean"},
    {"url": "https://www.endmigra.com/", "cat": "tld", "label": "Endmigra"},
    {"url": "https://www.greenpura.com/", "cat": "tld", "label": "Greenpura"},
    {"url": "https://www.colopril.us/", "cat": "tld", "label": "Colopril US"},
    {"url": "https://www.bonexcin.us/", "cat": "tld", "label": "Bonexcin US"},
    {"url": "https://www.somulin.store/", "cat": "tld", "label": "Somulin Store"},
    {"url": "https://www.myprovasil.com/", "cat": "tld", "label": "MyProvasil"},
    {"url": "https://www.vazopril.com/", "cat": "tld", "label": "Vazopril"},
    {"url": "https://www.vazoprilstore.com/", "cat": "tld", "label": "Vazopril Store"},
    {"url": "https://www.flexdermalstore.com/", "cat": "tld", "label": "Flexdermal Store"},
    {"url": "https://www.zenofemstore.com/", "cat": "tld", "label": "Zenofem Store"},
    {"url": "https://menoquil.pharmaxalabs.com/", "cat": "kill", "label": "Menoquil Kill"},
    {"url": "https://provasil.pharmaxalabs.com/", "cat": "kill", "label": "Provasil Kill"},
    {"url": "https://www.phenocalstore.com/", "cat": "kill", "label": "Phenocal Kill"},
    {"url": "https://serelax.pharmaxalabs.com/", "cat": "kill", "label": "Serelax Kill"},
    {"url": "https://somulin.pharmaxalabs.com/", "cat": "kill", "label": "Somulin Kill"},
    {"url": "https://prostara.pharmaxalabs.com/", "cat": "kill", "label": "Prostara Kill"},
    {"url": "https://colopril.pharmaxalabs.com/", "cat": "kill", "label": "Colopril Kill"},
    {"url": "https://flexdermal.pharmaxalabs.com/", "cat": "kill", "label": "Flexdermal Kill"},
    {"url": "https://zenofem.pharmaxalabs.com/", "cat": "kill", "label": "Zenofem Kill"},
    {"url": "https://zenogel.pharmaxalabs.com/", "cat": "kill", "label": "Zenogel Kill"},
    {"url": "https://bonexcin.pharmaxalabs.com/", "cat": "kill", "label": "Bonexcin Kill"},
    {"url": "https://vazopril.pharmaxalabs.com/", "cat": "kill", "label": "Vazopril Kill"},
    {"url": "https://glucoeze.pharmaxalabs.com/", "cat": "kill", "label": "Glucoeze Kill"},
    {"url": "https://nufolix.pharmaxalabs.com/", "cat": "kill", "label": "Nufolix Kill"},
    {"url": "https://nutesta.pharmaxalabs.com/", "cat": "kill", "label": "Nutesta Kill"},
    {"url": "https://ocuvital.pharmaxalabs.com/", "cat": "kill", "label": "Ocuvital Kill"},
    {"url": "https://zenotone.pharmaxalabs.com/", "cat": "kill", "label": "Zenotone Kill"},
    {"url": "https://maxolean.pharmaxalabs.com/", "cat": "kill", "label": "Maxolean Kill"},
    {"url": "https://endmigra.pharmaxalabs.com/", "cat": "kill", "label": "Endmigra Kill"},
    {"url": "https://products.solvadermstore.com/", "cat": "solv_kill", "label": "Solvaderm Products"},
    {"url": "https://products.solvadermstore.com/ace-ferulic/", "cat": "solv_kill", "label": "Ace Ferulic Kill"},
    {"url": "https://products.solvadermstore.com/stemnucell/", "cat": "solv_kill", "label": "Stemnucell Kill"},
    {"url": "https://products.solvadermstore.com/revivatone/", "cat": "solv_kill", "label": "Revivatone Kill"},
    {"url": "https://products.solvadermstore.com/juvabrite/", "cat": "solv_kill", "label": "Juvabrite Kill"},
    {"url": "https://products.solvadermstore.com/universal-tinted-moisturizer/", "cat": "solv_kill", "label": "UTM Kill"},
    {"url": "https://products.nuu3.com/", "cat": "nuu3_kill", "label": "Nuu3 Products"},
    {"url": "https://products.nuu3.com/natures-superfuel/", "cat": "nuu3_kill", "label": "Superfuel Kill"},
    {"url": "https://products.nuu3.com/acv-gummies/", "cat": "nuu3_kill", "label": "ACV Gummies Kill"},
    {"url": "https://products.nuu3.com/gut-health-365/", "cat": "nuu3_kill", "label": "Gut Health Kill"},
    {"url": "https://products.nuu3.com/sleep-support-gummies/", "cat": "nuu3_kill", "label": "Sleep Support Kill"},
    {"url": "https://products.nuu3.com/liver-health-365/", "cat": "nuu3_kill", "label": "Liver Health Kill"},
]

TIER3 = [
    {"url": "https://www.totalhealthreports.us/", "cat": "ppc", "label": "Total Health Reports"},
    {"url": "https://blog.totalhealthreports.us/", "cat": "ppc", "label": "THR Blog"},
    {"url": "https://news.totalhealthreports.us/", "cat": "ppc", "label": "THR News"},
    {"url": "https://beauty.totalhealthreports.us/", "cat": "ppc", "label": "THR Beauty"},
    {"url": "https://reviews.totalhealthreports.us/", "cat": "ppc", "label": "THR Reviews"},
    {"url": "https://nutrition.totalhealthreports.us/", "cat": "ppc", "label": "THR Nutrition"},
    {"url": "https://www.trustedhealthanswers.com/", "cat": "ppc", "label": "Trusted Health Answers"},
    {"url": "https://www.healthwebmagazine.com/", "cat": "seo", "label": "Health Web Magazine"},
    {"url": "https://www.skinformulations.com/", "cat": "seo", "label": "Skin Formulations"},
    {"url": "https://www.virectin.us/", "cat": "seo", "label": "Virectin US"},
    {"url": "https://www.totalhealthreports.com/", "cat": "seo", "label": "THR .com"},
]


# ── Check Functions ──────────────────────────────────────────────────────

def check_http(url):
    try:
        start = time.time()
        r = req.get(url, headers=HDRS, timeout=TIMEOUT, allow_redirects=True)
        return {"code": r.status_code, "time": round(time.time() - start, 2), "ok": r.status_code == 200, "html": r.text}
    except req.exceptions.SSLError as e:
        return {"code": None, "err": f"SSL: {str(e)[:80]}", "ok": False, "html": ""}
    except req.exceptions.ConnectionError as e:
        return {"code": None, "err": f"Conn: {str(e)[:80]}", "ok": False, "html": ""}
    except req.exceptions.Timeout:
        return {"code": None, "err": "Timeout >8s", "ok": False, "html": ""}
    except Exception as e:
        return {"code": None, "err": str(e)[:80], "ok": False, "html": ""}


def check_ssl(url):
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
    issues = []
    # Title
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        t = m.group(1).strip()
        if len(t) < 10:
            issues.append(("warning", f"Title too short ({len(t)} chars)"))
    else:
        issues.append(("critical", "Missing <title> tag"))

    # Meta description
    d = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.I)
    if not d:
        d = re.search(r'<meta\s+content=["\'](.*?)["\']\s+name=["\']description["\']', html, re.I)
    if not d:
        issues.append(("warning", "Missing meta description"))

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

    # Schema
    if not re.search(r'application/ld\+json', html, re.I):
        issues.append(("info", "No JSON-LD schema"))

    # Mixed content
    if url.startswith("https"):
        mc = re.findall(r'(?:src|href)=["\']http://(?!localhost)', html, re.I)
        if mc:
            issues.append(("warning", f"Mixed content: {len(mc)} HTTP resources"))

    # Placeholder text
    if "lorem ipsum" in html.lower():
        issues.append(("critical", "Lorem Ipsum placeholder text found"))

    # Images missing alt
    imgs = re.findall(r"<img\s+[^>]*?>", html, re.I)
    no_alt = [i for i in imgs if 'alt=' not in i.lower()]
    if no_alt:
        issues.append(("warning", f"{len(no_alt)}/{len(imgs)} images missing alt text"))

    # Sitemap
    if not re.search(r'sitemap', html, re.I):
        pass  # Check separately for Tier 1

    return issues


def audit_site(site, tier):
    url = site["url"]
    r = {"url": url, "label": site["label"], "cat": site["cat"], "tier": tier, "issues": [], "resp_time": None}

    # HTTP check
    http = check_http(url)
    if not http["ok"]:
        r["issues"].append(("critical", http.get("err", f"HTTP {http.get('code')}")))
        r["status"] = "DOWN"
        return r

    r["resp_time"] = http["time"]
    if http["time"] > 5:
        r["issues"].append(("warning", f"Slow: {http['time']}s"))

    # SSL check
    s = check_ssl(url)
    if not s["ok"]:
        r["issues"].append(("critical", f"SSL: {s.get('err', 'failed')}"))
    elif s.get("warn"):
        r["issues"].append(("critical", f"SSL expires in {s['days']} days!"))

    # Meta checks
    if http["html"]:
        r["issues"].extend(check_meta(http["html"], url))

        # Tier 1: extra checks
        if tier == 1:
            html = http["html"]
            # CTA check for stores/kill pages
            if site["cat"] in ("shopify", "kill", "solv_kill", "nuu3_kill"):
                if not re.search(r"(?:buy.now|add.to.cart|order.now|shop.now)", html, re.I):
                    r["issues"].append(("warning", "No CTA button found (Buy Now / Add to Cart)"))
            # Page size
            kb = len(html) / 1024
            if kb > 500:
                r["issues"].append(("info", f"Large HTML: {round(kb)}KB"))

    # Determine status
    crits = sum(1 for t, _ in r["issues"] if t == "critical")
    warns = sum(1 for t, _ in r["issues"] if t == "warning")
    r["status"] = "CRITICAL" if crits else ("WARNING" if warns else "PASS")
    return r


# ── Run All ──────────────────────────────────────────────────────────────

def run_audit():
    start = time.time()
    results = {"tier1": [], "tier2": [], "tier3": []}

    # Tier 1: sequential deep audit
    for s in TIER1:
        results["tier1"].append(audit_site(s, 1))

    # Tier 2: parallel standard
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(audit_site, s, 2): s for s in TIER2}
        for f in concurrent.futures.as_completed(futs):
            results["tier2"].append(f.result())

    # Tier 3: parallel light
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
        "issues": sum(len(r["issues"]) for r in all_r),
        "duration": round(time.time() - start),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    return results


# ── PDF Generation ───────────────────────────────────────────────────────

def generate_pdf(results):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch, leftMargin=0.7*inch, rightMargin=0.7*inch)
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle("CT", parent=styles["Title"], fontSize=26, textColor=HexColor("#1a1a2e"), alignment=TA_CENTER, spaceAfter=6))
    styles.add(ParagraphStyle("CS", parent=styles["Normal"], fontSize=13, textColor=HexColor("#666"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("SH", parent=styles["Heading1"], fontSize=15, textColor=HexColor("#1a1a2e"), spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle("IT", parent=styles["Normal"], fontSize=9, leading=12, spaceBefore=1, spaceAfter=1))
    styles.add(ParagraphStyle("SM", parent=styles["Normal"], fontSize=8, leading=10, textColor=HexColor("#888")))

    s = results["summary"]
    story = []

    # Cover
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph("Weekend QA Audit Report", styles["CT"]))
    story.append(Paragraph(f"{s['date']} | {s['total']} Sites Checked", styles["CS"]))
    story.append(Paragraph("PharmaxaLabs / Solvaderm / Nuu3", styles["CS"]))
    story.append(Spacer(1, 0.4*inch))

    stat_data = [
        [Paragraph(f"<font size='22'>{s['total']}</font>", styles["CS"]),
         Paragraph(f"<font size='22' color='#c62828'>{s['critical']}</font>", styles["CS"]),
         Paragraph(f"<font size='22' color='#f57f17'>{s['warning']}</font>", styles["CS"]),
         Paragraph(f"<font size='22' color='#2e7d32'>{s['passed']}</font>", styles["CS"]),
         Paragraph(f"<font size='22' color='#b71c1c'>{s['down']}</font>", styles["CS"])],
        [Paragraph("Checked", styles["SM"]), Paragraph("Critical", styles["SM"]),
         Paragraph("Warnings", styles["SM"]), Paragraph("Passed", styles["SM"]),
         Paragraph("Down", styles["SM"])],
    ]
    st = Table(stat_data, colWidths=[1.3*inch]*5)
    st.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,0),10),("BOTTOMPADDING",(0,1),(-1,1),10),
        ("LINEBELOW",(0,0),(-1,0),0.5,HexColor("#e0e0e0"))]))
    story.append(st)
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(f"Duration: {s['duration']}s | Total issues: {s['issues']}", styles["SM"]))
    story.append(PageBreak())

    # Critical issues
    story.append(Paragraph("Critical Issues", styles["SH"]))
    all_r = results["tier1"] + results["tier2"] + results["tier3"]
    crit_sites = [r for r in all_r if r["status"] in ("CRITICAL", "DOWN")]
    if not crit_sites:
        story.append(Paragraph('<font color="#2e7d32">No critical issues. All sites operational.</font>', styles["IT"]))
    else:
        for site in crit_sites:
            story.append(Paragraph(f'<font color="#c62828">[{site["status"]}]</font> <b>{site["label"]}</b> — <font color="#888">{site["url"]}</font>', styles["IT"]))
            for typ, msg in site["issues"]:
                if typ == "critical":
                    story.append(Paragraph(f'&nbsp;&nbsp;&nbsp;<font color="#c62828">* {msg[:90]}</font>', styles["IT"]))
            story.append(Spacer(1, 4))
    story.append(PageBreak())

    # Tier sections
    def add_tier(tier_results, name):
        story.append(Paragraph(name, styles["SH"]))
        hdr = ["Site", "Status", "Time", "Issues"]
        rows = [hdr]
        status_order = {"DOWN": 0, "CRITICAL": 1, "WARNING": 2, "PASS": 3}
        for site in sorted(tier_results, key=lambda x: status_order.get(x["status"], 4)):
            rt = f"{site['resp_time']}s" if site.get("resp_time") else "N/A"
            ci = sum(1 for t, _ in site["issues"] if t == "critical")
            wi = sum(1 for t, _ in site["issues"] if t == "warning")
            isum = []
            if ci: isum.append(f"{ci}C")
            if wi: isum.append(f"{wi}W")
            sc = {"CRITICAL": "#c62828", "WARNING": "#f57f17", "PASS": "#2e7d32", "DOWN": "#b71c1c"}.get(site["status"], "#888")
            rows.append([
                Paragraph(f'<font size="8">{site["label"][:35]}</font>', styles["IT"]),
                Paragraph(f'<font size="8" color="{sc}">[{site["status"]}]</font>', styles["IT"]),
                Paragraph(f'<font size="8">{rt}</font>', styles["IT"]),
                Paragraph(f'<font size="8">{" / ".join(isum) if isum else "Clean"}</font>', styles["IT"]),
            ])
        t = Table(rows, colWidths=[2.5*inch, 1.2*inch, 0.8*inch, 1.2*inch], repeatRows=1)
        ts = [("BACKGROUND",(0,0),(-1,0),HexColor("#1a1a2e")),("TEXTCOLOR",(0,0),(-1,0),white),
              ("FONTSIZE",(0,0),(-1,0),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
              ("ALIGN",(1,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
              ("GRID",(0,0),(-1,-1),0.5,HexColor("#e0e0e0")),
              ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),4)]
        for i in range(2, len(rows), 2):
            ts.append(("BACKGROUND",(0,i),(-1,i),HexColor("#f5f5f5")))
        t.setStyle(TableStyle(ts))
        story.append(t)
        story.append(Spacer(1, 8))

        # Issue details for problem sites
        probs = [r for r in tier_results if r["issues"]]
        if probs:
            story.append(Paragraph("Issue Details:", styles["SH"]))
            for site in probs:
                els = [Paragraph(f'<b>{site["label"]}</b> ({site["url"]})', styles["IT"])]
                for typ, msg in site["issues"][:6]:
                    c = {"critical": "#c62828", "warning": "#f57f17", "info": "#1565c0"}.get(typ, "#888")
                    els.append(Paragraph(f'&nbsp;&nbsp;<font color="{c}">[{typ.upper()}]</font> {msg[:85]}', styles["IT"]))
                els.append(Spacer(1, 4))
                story.append(KeepTogether(els))

    add_tier(results["tier1"], "Tier 1 — High Priority (Deep Audit)")
    story.append(PageBreak())
    add_tier(results["tier2"], "Tier 2 — Medium Priority (Standard Audit)")
    story.append(PageBreak())
    add_tier(results["tier3"], "Tier 3 — PPC & SEO (Light Audit)")

    story.append(Spacer(1, 0.4*inch))
    story.append(Paragraph(f"Auto-generated {s['date']} by Weekend QA Bot. Scan: {s['duration']}s.", styles["SM"]))

    doc.build(story)
    buf.seek(0)
    return buf


# ── Slack ────────────────────────────────────────────────────────────────

def post_slack(results, pdf_buf):
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return False

    s = results["summary"]
    all_r = results["tier1"] + results["tier2"] + results["tier3"]

    # Critical items
    crits = []
    for site in all_r:
        if site["status"] in ("CRITICAL", "DOWN"):
            for t, m in site["issues"]:
                if t == "critical":
                    crits.append(f"  *{site['label']}*: {m[:70]}")
                    break
            else:
                crits.append(f"  *{site['label']}*: Site DOWN")
    crit_text = "\n".join(crits[:10]) if crits else "  None — all clear!"

    # Tier 1 status
    t1 = []
    for site in results["tier1"]:
        ico = {"PASS": ":white_check_mark:", "WARNING": ":warning:", "CRITICAL": ":red_circle:", "DOWN": ":x:"}.get(site["status"], ":grey_question:")
        t1.append(f"  {ico} {site['label']}")

    msg = (
        f":mag: *Weekend QA Audit Report — {s['date']}*\n\n"
        f"<@{AMIT_ID}> Here's your automated QA report:\n\n"
        f"*Summary:*\n"
        f"  :bar_chart: Sites Checked: *{s['total']}*\n"
        f"  :red_circle: Critical: *{s['critical']}*\n"
        f"  :warning: Warnings: *{s['warning']}*\n"
        f"  :white_check_mark: Passed: *{s['passed']}*\n"
        f"  :x: Down: *{s['down']}*\n\n"
        f"*Top Critical Issues:*\n{crit_text}\n\n"
        f"*Tier 1 Status:*\n" + "\n".join(t1) + "\n\n"
        f":clock1: Scan: {s['duration']}s | _Automated Saturday 8am_"
    )

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Post message
    r = req.post("https://slack.com/api/chat.postMessage", headers=hdrs,
                  json={"channel": SLACK_CHANNEL, "text": msg, "unfurl_links": False})

    if not (r.status_code == 200 and r.json().get("ok")):
        return False
    thread_ts = r.json().get("ts")

    # Upload PDF
    if pdf_buf:
        uh = {"Authorization": f"Bearer {token}"}
        pdf_bytes = pdf_buf.read()
        fname = f"QA_Report_{s['date']}.pdf"

        # Get upload URL
        ur = req.post("https://slack.com/api/files.getUploadURLExternal",
                       headers=uh, data={"filename": fname, "length": len(pdf_bytes)})
        if ur.status_code == 200 and ur.json().get("ok"):
            upload_url = ur.json()["upload_url"]
            file_id = ur.json()["file_id"]
            # Upload
            req.post(upload_url, files={"file": (fname, pdf_bytes, "application/pdf")})
            # Complete
            req.post("https://slack.com/api/files.completeUploadExternal", headers=hdrs,
                      json={"files": [{"id": file_id, "title": f"QA Report {s['date']}"}],
                            "channel_id": SLACK_CHANNEL, "thread_ts": thread_ts,
                            "initial_comment": ":page_facing_up: Full PDF report attached."})
    return True


# ── Handler ──────────────────────────────────────────────────────────────

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
            # Run audit
            results = run_audit()

            # Generate PDF
            pdf_buf = generate_pdf(results)

            # Post to Slack
            slack_ok = post_slack(results, pdf_buf)

            # Respond
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
    print("Starting Weekend QA Audit...")
    results = run_audit()
    pdf_buf = generate_pdf(results)
    slack_ok = post_slack(results, pdf_buf)

    # Save PDF locally if OUTPUT_DIR is set
    output_dir = os.environ.get("OUTPUT_DIR")
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d")
        path = os.path.join(output_dir, f"qa-report-{ts}.pdf")
        with open(path, "wb") as f:
            pdf_buf.seek(0)
            f.write(pdf_buf.read())
        print(f"PDF saved to {path}")

    s = results["summary"]
    print(f"\nDone! {s['total']} sites checked — "
          f"{s['critical']} critical, {s['warning']} warnings, "
          f"{s['info']} info. Slack posted: {slack_ok}")
