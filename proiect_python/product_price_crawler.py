from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from typing import List, Optional
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# simplifica stocarea unui produs
@dataclass
class ProductInfo:
    query: str          
    name: str           
    min_price: float    
    max_price: float    
    offers: int         
    url: str           
    currency: str = "RON"


def setup_driver() -> webdriver.Chrome:
    """Configureaza si porneste Chrome pentru Selenium."""
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=options)


def parse_price(text: str) -> float:
    """
    Transforma texte:
        '3.569,90 RON'  -> 3569.90
        '2 799,00 lei'  -> 2799.00
        '4,50 RON'      -> 4.50
    intr-un float.
    """
    if not text:
        raise ValueError("empty price")

    clean = re.sub(r"[^\d.,]", "", text)

    if not clean:
        raise ValueError("no digits")

    # sterge punctul si inlocuieste virgula cu punct
    if "." in clean and "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    # doar virgule => tratam ca zecimal
    elif "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    else:
        # doar puncte; daca sunt mai multe, ultimul e zecimal
        if clean.count(".") > 1:
            parts = clean.split(".")
            clean = "".join(parts[:-1]) + "." + parts[-1]

    return float(clean)


def find_compari_url_via_google(driver: webdriver.Chrome, query: str) -> Optional[str]:
    """
    Caută pe Google: '<query> site:compari.ro' și întoarce
    primul link către compari.ro (ideal o pagină de produs '-p').
    """
    wait = WebDriverWait(driver, 15)

    search_term = f"{query} site:compari.ro"
    search_url = "https://www.google.com/search?q=" + quote_plus(search_term)
    print(f"[INFO] Google search URL: {search_url}")

    driver.get(search_url)

    # AICI poti avea login / captcha Google
    input("[INFO] Daca Google iti cere login / verificare, rezolva in fereastra Chrome, "
          "apoi apasa ENTER in terminal...")

    try:
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a")))
    except TimeoutException:
        print("[WARN] Google nu a incarcat rezultatele la timp.")
        return None

    links = driver.find_elements(By.CSS_SELECTOR, "a")

    # intai cautam link-uri compari.ro care par pagini de produs (contin '-p')
    for a in links:
        href = a.get_attribute("href") or ""
        if "compari.ro" in href and "-p" in href:
            print(f"[INFO] Gasit link compari.ro (produs): {href}")
            return href

    # fallback: orice link compari.ro
    for a in links:
        href = a.get_attribute("href") or ""
        if "compari.ro" in href:
            print(f"[INFO] Gasit link compari.ro: {href}")
            return href

    print("[WARN] Nu am gasit niciun link compari.ro in rezultate.")
    return None


def extract_product_info_from_compari(driver: webdriver.Chrome, query: str, url: str) -> Optional[ProductInfo]:
    """
    Avand URL de produs compari.ro, extrage:
      - nume
      - pret minim / maxim
      - numar de oferte
    """
    wait = WebDriverWait(driver, 15)

    driver.get(url)

    # AICI poate aparea verificarea de bot de la compari.ro
    input("[INFO] Daca compari.ro iti cere verificare (bot check / captcha), "
          "rezolva in fereastra Chrome, apoi apasa ENTER aici in terminal...")

    # Numele produsului (in general <h1>)
    try:
        name_elem = wait.until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        name = name_elem.text.strip()
    except TimeoutException:
        name = query

    # Textul intregii pagini, ca sa gasim preturi in el
    body_text = driver.find_element(By.TAG_NAME, "body").text

    raw_prices = re.findall(
        r"([\d\s.,]+)\s*(?:lei|RON)",
        body_text,
        flags=re.IGNORECASE,
    )

    parsed_prices: List[float] = []
    for p in raw_prices:
        try:
            val = parse_price(p)
            if val > 10:  # filtram zgomotul (preturi prea mici)
                parsed_prices.append(val)
        except ValueError:
            continue

    if not parsed_prices:
        print(f"[WARN] Nu am putut extrage preturi pentru: {query}")
        return None

    min_price = min(parsed_prices)
    max_price = max(parsed_prices)

    offers_match = re.search(
        r"(\d+)\s+ofert[eă]",
        body_text,
        flags=re.IGNORECASE,
    )
    if offers_match:
        offers = int(offers_match.group(1))
    else:
        offers = len(parsed_prices)

    return ProductInfo(
        query=query,
        name=name,
        min_price=min_price,
        max_price=max_price,
        offers=offers,
        url=url,
    )


def crawl_product(driver: webdriver.Chrome, query: str) -> Optional[ProductInfo]:
    """
    Pentru un query:
      1. cauta pe Google '<query> site:compari.ro'
      2. ia primul link compari.ro
      3. extrage informatia de pe pagina produsului
    """
    print(f"\n[INFO] Procesez: {query!r}")

    compari_url = find_compari_url_via_google(driver, query)
    if not compari_url:
        print(f"[WARN] Nu am gasit URL compari.ro pentru: {query}")
        return None

    return extract_product_info_from_compari(driver, query, compari_url)


def main() -> None:
    driver = setup_driver()

    queries = [
        "Apple iPhone 15 128GB",
        "Samsung Galaxy S24",
        "Ariston Clas One WiFi 24 kW (3302123)",
        "Lenovo Legion T5 30AGB10 90YJ0008RM",
    ]

    products: List[ProductInfo] = []

    try:
        for q in queries:
            product = crawl_product(driver, q)
            if product:
                products.append(product)
            time.sleep(2)
    finally:
        driver.quit()

    print("\n=== Rezultate Product Price Crawler ===\n")
    print(f"Produse gasite: {len(products)} din {len(queries)}\n")
    for p in products:
        print(f"Query:        {p.query}")
        print(f"Nume produs:  {p.name}")
        print(f"URL:          {p.url}")
        print(f"Pret minim:   {p.min_price:.2f} {p.currency}")
        print(f"Pret maxim:   {p.max_price:.2f} {p.currency}")
        print(f"Oferte:       {p.offers}")
        print("-" * 50)

    if products:
        with open("products.json", "w", encoding="utf-8") as f:
            json.dump(
                [asdict(p) for p in products],
                f,
                ensure_ascii=False,
                indent=4,
            )
        print("\n[INFO] Datele au fost salvate în products.json")
    else:
        print("\n[WARN] Nu s-au gasit produse de salvat")


if __name__ == "__main__":
    main()
