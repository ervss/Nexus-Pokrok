import requests
import time
import re
import xml.etree.ElementTree as ET

class WebshareSearcher:
    def __init__(self):
        # API endpointy
        self.search_url = "https://webshare.cz/api/search/"
        self.link_url = "https://webshare.cz/api/file_link/"
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        }
    
    def get_category_slug(self, choice):
        mapping = {
            '1': 'video',
            '2': 'adult',
            '3': 'audio',
            '4': 'archives',
            '5': ''
        }
        return mapping.get(choice, 'video')

    def clean_xml(self, xml_string):
        """Opraví bežné chyby vo Webshare XML odpovedi"""
        if not xml_string: return ""
        xml_string = re.sub(r'&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9a-fA-F]+);)', '&amp;', xml_string)
        xml_string = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\u10000-\u10FFFF]', '', xml_string)
        return xml_string

    def get_direct_link(self, ident, token):
        """Získa priamy VIP link pre daný súbor"""
        try:
            payload = {'ident': ident, 'wst': token}
            response = requests.post(self.link_url, data=payload, headers=self.headers)
            
            if response.status_code == 200:
                clean_xml = self.clean_xml(response.text)
                root = ET.fromstring(clean_xml)
                link_tag = root.find('link')
                if link_tag is not None and link_tag.text:
                    return link_tag.text
        except Exception as e:
            pass # Ignorujeme chyby pri resolveri, skúsime ďalší
        return None

    def search(self):
        print("="*45)
        print("   🚀 WEBSHARE VIP RESOLVER v6.0 (Direct Links)")
        print("="*45)

        query = input("Zadaj čo hľadáme: ").strip()
        
        print("\nVyber kategóriu:")
        print("1 - Video (Filmy/Seriály)")
        print("2 - XXX (Adult)")
        print("3 - Hudba")
        print("4 - Software/Hry/Archívy")
        print("5 - Všetko")
        cat_choice = input("Tvoja voľba (predvolené 1): ").strip() or '1'
        category = self.get_category_slug(cat_choice)

        try:
            min_size_mb = int(input("Minimálna veľkosť v MB [Enter pre 0]: ") or 0)
        except ValueError:
            min_size_mb = 0

        try:
            target_count = int(input("Koľko linkov chceš nájsť? (napr. 20): ") or 20)
        except ValueError:
            target_count = 20

        # Tvoj token napevno
        vip_token = 'moXMvKrXWIA5zqbY'

        print(f"\n📡 Hľadám '{query}' v kategórii [{category if category else 'ALL'}] (> {min_size_mb} MB).")
        print(f"🔄 Zároveň generujem priame VIP linky...")
        print(f"🎯 Cieľ: {target_count} linkov.\n")

        found_links = []
        offset = 0
        limit_per_req = 25 # Menej, aby sme stíhali resolvovať linky

        while len(found_links) < target_count:
            try:
                payload = {
                    'what': query,
                    'category': category,
                    'sort': 'relevance',
                    'offset': offset,
                    'limit': limit_per_req,
                    'wst': vip_token
                }

                response = requests.post(self.search_url, data=payload, headers=self.headers)
                
                if response.status_code != 200:
                    print(f"❌ Chyba spojenia: {response.status_code}")
                    break
                
                clean_response_text = self.clean_xml(response.text)
                try:
                    root = ET.fromstring(clean_response_text)
                except ET.ParseError:
                    break

                files = root.findall('file')
                if not files:
                    if offset == 0: print("⚠️ Žiadne výsledky.")
                    break

                for file in files:
                    if len(found_links) >= target_count:
                        break

                    try:
                        name_el = file.find('name')
                        ident_el = file.find('ident')
                        size_el = file.find('size')

                        if name_el is None or ident_el is None: continue

                        name = name_el.text
                        ident = ident_el.text
                        size_bytes = int(size_el.text) if size_el is not None and size_el.text else 0
                        size_mb = int(size_bytes / (1024 * 1024))

                        if size_mb >= min_size_mb:
                            # 🛑 TU JE ZMENA: Okamžite získame priamy link
                            direct_link = self.get_direct_link(ident, vip_token)
                            
                            if direct_link:
                                # Ukladáme len čistý link, presne ako v súbore 199
                                found_links.append(direct_link)
                                
                                # Výpis do konzoly
                                short_name = (name[:40] + '...') if len(name) > 40 else name
                                print(f"   [OK] {len(found_links)}/{target_count}: {short_name} ({size_mb} MB) -> LINK OK")
                            else:
                                print(f"   [SKIP] {short_name} - Nepodarilo sa získať VIP link")

                    except Exception:
                        continue 

                offset += limit_per_req
                time.sleep(0.5) # Pauza, aby sme nezahltili server

            except Exception as e:
                print(f"❌ Chyba: {e}")
                break

        if found_links:
            filename = f"ws_links_{int(time.time())}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                # Zapíšeme len čisté linky, každý na nový riadok
                f.write('\n'.join(found_links))
            
            print("-" * 45)
            print(f"🎉 HOTOVO! Našlo sa {len(found_links)} priamych VIP linkov.")
            print(f"📂 Súbor pre dashboard: {filename}")
        else:
            print("-" * 45)
            print("❌ Nenašli sa žiadne linky.")

if __name__ == "__main__":
    app = WebshareSearcher()
    app.search()
    input("\nStlač Enter pre ukončenie...")