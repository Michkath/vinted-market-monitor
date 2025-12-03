# main.py
import os
import time
import json
import requests
import random
import re
from datetime import datetime
from urllib.parse import quote_plus
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# On utilise SB pour le mode "Undetected"
from seleniumbase import SB 

load_dotenv()

# --- CONFIGURATION ---
PROJECT_URL = os.getenv("PROJECT_URL")
API_KEY = os.getenv("API_KEY")
TABLE_NAME = os.getenv("TABLE_NAME", "vinted_raw")
SEARCH_QUERY = os.getenv("SEARCH_QUERY", "jupe zara")
MAX_PAGES = int(os.getenv("MAX_PAGES", "2"))

headers = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation"
}

# --- FONCTIONS UTILITAIRES ---

def clean_price(price_raw):
    """Nettoie le prix pour le transformer en float."""
    if not price_raw: 
        return None
    s = price_raw.strip().replace("€", "").replace("\u202f", "").replace(" ", "").replace(",", ".")
    try:
        match = re.search(r"(\d+(\.\d+)?)", s)
        if match:
            return float(match.group(1))
        return None
    except:
        return None

def parse_details(full_text):
    """
    Découpe la chaîne longue de Vinted pour extraire Marque, Taille, État.
    Ex: "Jupe Zara, marque: Zara, état: Très bon état, taille: S / 36 / 8..."
    """
    details = {
        "title": None,
        "brand": None,
        "condition": None,
        "size": None
    }
    
    if not full_text:
        return details

    # 1. Extraction de la MARQUE
    # On cherche "marque: Quelque Chose,"
    brand_match = re.search(r"marque:\s*(.*?)(,|$)", full_text, re.IGNORECASE)
    if brand_match:
        details["brand"] = brand_match.group(1).strip()

    # 2. Extraction de la TAILLE
    size_match = re.search(r"taille:\s*(.*?)(,|$)", full_text, re.IGNORECASE)
    if size_match:
        details["size"] = size_match.group(1).strip()

    # 3. Extraction de l'ÉTAT
    condition_match = re.search(r"état:\s*(.*?)(,|$)", full_text, re.IGNORECASE)
    if condition_match:
        details["condition"] = condition_match.group(1).strip()

    # 4. Nettoyage du TITRE
    # Le titre est généralement tout ce qui se trouve AVANT la première virgule ou le premier mot-clé "marque:"
    # On coupe au premier mot clé trouvé
    split_keys = ["marque:", "taille:", "état:", ","]
    temp_title = full_text
    
    for key in split_keys:
        if key in temp_title:
            temp_title = temp_title.split(key)[0]
    
    details["title"] = temp_title.strip()
    
    return details

def upsert_items(items):
    """Envoie les données vers Supabase via API REST."""
    if not items:
        print("⚠️ Aucun item à envoyer.")
        return

    print(f"📡 Envoi de {len(items)} items vers Supabase...")
    url = f"{PROJECT_URL}/rest/v1/{TABLE_NAME}?on_conflict=item_id"
    
    try:
        r = requests.post(url, headers=headers, data=json.dumps(items))
        if r.status_code in (200, 201, 204):
            print(f"✅ Succès ! Données enregistrées.")
        else:
            print(f"❌ Erreur API Supabase: {r.status_code}")
    except Exception as e:
        print(f"❌ Exception lors de l'envoi: {e}")

# --- SCRAPING AVEC BEAUTIFUL SOUP ---

def extract_with_bs4(html_content):
    """
    Analyse le HTML brut avec BeautifulSoup.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    items = []
    
    print("🕵️  Analyse HTML avec BeautifulSoup...")
    
    # On cherche toutes les divs qui ressemblent à des cartes
    cards = soup.find_all("div", class_="feed-grid__item")
    print(f"📦 {len(cards)} cartes trouvées dans le HTML.")

    for i, card in enumerate(cards):
        try:
            # 1. RECUPERATION DU TEXTE "RICHE" (Title + Metadata)
            # Vinted met souvent toutes les infos dans l'attribut 'title' du lien
            link_tag = card.find("a", href=lambda href: href and "/items/" in href)
            
            raw_info_string = ""
            url = None
            item_id = None
            photo_url = None
            
            if link_tag:
                url = link_tag['href']
                # C'est ici que se cache la mine d'or (Marque, Taille, etc.)
                raw_info_string = link_tag.get('title', '')
                
                # Si le title est vide, on essaie l'image alt
                if not raw_info_string:
                    img_tag = card.find("img")
                    if img_tag:
                        raw_info_string = img_tag.get('alt', '')
                        photo_url = img_tag.get("src")
                else:
                    # On essaie quand même de chopper la photo
                    img_tag = card.find("img")
                    if img_tag:
                        photo_url = img_tag.get("src")

                # Extraction ID
                parts = url.split("/")
                for p in parts:
                    clean_p = p.split("-")[0]
                    if clean_p.isdigit():
                        item_id = clean_p
                        break

            # 2. PARSING DES DETAILS (Marque, Taille, Etat)
            parsed = parse_details(raw_info_string)

            # 3. PRIX
            text_content = card.get_text(separator=" ", strip=True)
            price = None
            price_match = re.search(r"(\d+[,.]\d{2})\s?€", text_content)
            if price_match:
                price = clean_price(price_match.group(0))

            # VALIDATION
            if item_id and url and price:
                items.append({
                    "item_id": item_id,
                    "title": parsed["title"] or "Titre Inconnu",
                    "brand": parsed["brand"],       # Nouveau
                    "size": parsed["size"],         # Nouveau
                    "condition": parsed["condition"],# Nouveau
                    "price": price,
                    "url": url,
                    "photo_url": photo_url,
                    "scraped_at": datetime.utcnow().isoformat()
                })
                
                if i < 3:
                     print(f"  ✅ {parsed['title']} | Marque: {parsed['brand']} | Taille: {parsed['size']} | {price}€")
            
        except Exception as e:
            continue
            
    return items

def main():
    print(f"🚀 Démarrage du scraper pour : '{SEARCH_QUERY}'")
    encoded_query = quote_plus(SEARCH_QUERY)
    all_unique_items = {} 
    
    with SB(uc=True, headless=False) as sb:
        # Gestion cookies
        try:
            sb.open("https://www.vinted.fr")
            sb.sleep(2)
            if sb.is_element_visible("#onetrust-accept-btn-handler"):
                sb.click("#onetrust-accept-btn-handler")
        except:
            pass

        for page in range(1, MAX_PAGES + 1):
            url = f"https://www.vinted.fr/catalog?search_text={encoded_query}&page={page}&order=newest_first"
            print(f"📄 Ouverture Page {page}...")
            sb.open(url)
            sb.sleep(random.uniform(3.0, 5.0))
            
            html = sb.get_page_source()
            page_items = extract_with_bs4(html)
            
            print(f"   -> {len(page_items)} items extraits.")
            for item in page_items:
                all_unique_items[item['item_id']] = item
                
    final_list = list(all_unique_items.values())
    print(f"🏁 Total final : {len(final_list)} items uniques.")
    
    if final_list:
        upsert_items(final_list)
    else:
        print("Rien à envoyer.")

if __name__ == "__main__":
    main()