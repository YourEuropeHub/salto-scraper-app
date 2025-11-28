from flask import Flask, Response, send_file
import csv
import time
import requests
from bs4 import BeautifulSoup
import re
import json
import io
from datetime import datetime

app = Flask(__name__)

BASE_LIST_URL = "https://www.salto-youth.net/tools/european-training-calendar/browse/?page={page}"
BASE_URL = "https://www.salto-youth.net"

scraped_data = []


def parse_list_page(html):
    soup = BeautifulSoup(html, "html.parser")
    events = []

    for h3 in soup.find_all("h3"):
        a = h3.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        url = BASE_URL + a["href"]
        block = h3.parent
        text = block.get_text("
", strip=True)

        lines = [l for l in text.split("
") if l.strip()]
        try:
            idx = lines.index(title)
        except ValueError:
            continue

        type_ = dates = location = app_deadline = ""

        if idx > 0:
            type_ = lines[idx-1]
        if idx + 1 < len(lines):
            dates = lines[idx+1]
        if idx + 2 < len(lines):
            location = lines[idx+2]

        for l in lines:
            if "Application deadline" in l:
                app_deadline = l.split(":", 1)[-1].strip()
                break

        events.append({
            "title": title,
            "type": type_,
            "dates": dates,
            "location": location,
            "application_deadline": app_deadline,
            "detail_url": url,
        })
    return events


def parse_detail_page(html, detail_url):
    soup = BeautifulSoup(html, "html.parser")

    def section_after(text):
        h = soup.find(lambda tag: tag.name and tag.name.startswith("h") and text in tag.get_text())
        if not h:
            return ""
        parts = []
        for sib in h.find_next_siblings():
            if sib.name and sib.name.startswith("h"):
                break
            parts.append(sib.get_text(" ", strip=True))
        return " ".join(parts).strip()

    training_overview = section_after("Training overview")
    p_text = training_overview

    participants_no = ""
    participants_from = ""
    recommended_for = ""
    accessibility = ""
    working_lang = ""
    organiser = ""
    participation_fee = section_after("Participation fee")
    accom_food = section_after("Accommodation and food")
    travel_reimb = section_after("Travel reimbursement")

    for line in p_text.splitlines():
        line = line.strip()
        if line.lower().startswith("for ") and "participants" in line.lower():
            participants_no = line.replace("for", "").replace("participants", "").strip()
        if line.startswith("from "):
            participants_from = line.replace("from", "").strip()
        if line.startswith("and recommended for"):
            recommended_for = line.replace("and recommended for", "").strip()
        if "Working language(s):" in line:
            working_lang = line.split("Working language(s):", 1)[-1].strip()

    acc_h = soup.find(lambda tag: tag.name and tag.name.startswith("h") and "Accessibility info" in tag.get_text())
    if acc_h:
        acc_text = []
        for sib in acc_h.find_next_siblings():
            if sib.name and sib.name.startswith("h"):
                break
            acc_text.append(sib.get_text(" ", strip=True))
        accessibility = " ".join(acc_text).strip()

    org_h = soup.find(lambda tag: tag.name and tag.name.startswith("h") and "Organiser" in tag.get_text())
    if org_h:
        p = org_h.find_next("p")
        if p:
            organiser = p.get_text(" ", strip=True)

    infopack_links = []
    downloads_h = soup.find(lambda tag: tag.name and "Available downloads" in tag.get_text())
    if downloads_h:
        for sib in downloads_h.find_next_siblings():
            if sib.name and sib.name.startswith("h"):
                break
            links = sib.find_all("a", href=True)
            for link in links:
                href = link["href"]
                if not href.startswith("http"):
                    href = BASE_URL + href
                link_text = link.get_text(strip=True)
                infopack_links.append(f"{link_text}: {href}")

    infopack_downloads = " | ".join(infopack_links) if infopack_links else ""

    application_procedure_url = ""
    apply_link = soup.find("a", string=re.compile(r"Apply now!", re.IGNORECASE))
    if apply_link and apply_link.get("href"):
        app_href = apply_link["href"]
        if not app_href.startswith("http"):
            app_href = BASE_URL + app_href
        application_procedure_url = app_href

    return {
        "participants_no": participants_no,
        "participants_from": participants_from,
        "recommended_for": recommended_for,
        "accessibility": accessibility,
        "working_language": working_lang,
        "organiser": organiser,
        "participation_fee": participation_fee,
        "accommodation_food": accom_food,
        "travel_reimbursement": travel_reimb,
        "infopack_downloads": infopack_downloads,
        "application_procedure_url": application_procedure_url,
    }


def get_external_application_link(application_procedure_url):
    if not application_procedure_url:
        return ""
    try:
        resp = requests.get(application_procedure_url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        external_link = soup.find("a", string=re.compile(r"Proceed to the external", re.IGNORECASE))
        if external_link and external_link.get("href"):
            return external_link["href"]
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(domain in href for domain in ["forms.gle", "google.com/forms", "typeform.com", "surveymonkey.com", "jotform.com"]):
                return href
        return ""
    except Exception:
        return ""


def scrape_events():
    global scraped_data
    scraped_data = []
    all_events = []

    for page in range(1, 7):
        yield f"data: {json.dumps({'type': 'log', 'message': f'Caricamento pagina {page}/6...', 'level': 'info'})}

"
        try:
            resp = requests.get(BASE_LIST_URL.format(page=page), timeout=15)
            resp.raise_for_status()
            events = parse_list_page(resp.text)
            all_events.extend(events)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'log', 'message': f'Errore pagina {page}: {str(e)}', 'level': 'error'})}

"

    total = len(all_events)
    yield f"data: {json.dumps({'type': 'log', 'message': f'Trovati {total} eventi. Inizio estrazione dettagli...', 'level': 'success'})}

"

    for idx, ev in enumerate(all_events, 1):
        yield f"data: {json.dumps({'type': 'log', 'message': f'[{idx}/{total}] {ev['title']}', 'level': 'info'})}

"
        try:
            dresp = requests.get(ev["detail_url"], timeout=15)
            dresp.raise_for_status()
            detail = parse_detail_page(dresp.text, ev["detail_url"])
            if detail["application_procedure_url"]:
                external_form_link = get_external_application_link(detail["application_procedure_url"])
                detail["application_form_link"] = external_form_link
            else:
                detail["application_form_link"] = ""
            row = {**ev, **detail}
            scraped_data.append(row)
            yield f"data: {json.dumps({'type': 'progress', 'current': idx, 'total': total})}

"
            time.sleep(0.3)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'log', 'message': f'Errore: {str(e)}', 'level': 'error'})}

"

    preview = scraped_data[:10]
    yield f"data: {json.dumps({'type': 'complete', 'count': len(scraped_data), 'preview': preview})}

"


@app.route('/')
def index():
    with open('index.html', 'r', encoding='utf-8') as f:
        return f.read()


@app.route('/scrape', methods=['POST'])
def scrape():
    return Response(scrape_events(), mimetype='text/event-stream')


@app.route('/download')
def download():
    if not scraped_data:
        return "No data available", 404

    output = io.StringIO()
    fieldnames = [
        "title", "type", "dates", "location", "application_deadline",
        "participants_no", "participants_from", "recommended_for",
        "accessibility", "working_language", "organiser",
        "participation_fee", "accommodation_food", "travel_reimbursement",
        "infopack_downloads", "application_form_link",
        "detail_url",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(scraped_data)
    output.seek(0)

    bytes_output = io.BytesIO()
    bytes_output.write(output.getvalue().encode('utf-8-sig'))
    bytes_output.seek(0)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'salto_events_{timestamp}.csv'

    return send_file(bytes_output, mimetype='text/csv', as_attachment=True, download_name=filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
