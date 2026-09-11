#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROSPECTOR V1 - Robot de prospecao de websites (GD Advertising)
================================================================
Recebe:  CATEGORIA + PAIS + PALAVRAS-CHAVE
Devolve: lista .txt de dominios (1 por linha) pronta a meter no robot de scraping,
         + um CSV com detalhe/score de cada site encontrado.

Filosofia: nao depende do SimilarWeb. Ataca por 7 vias diferentes para apanhar
o "long tail" de sites com trafego que nao aparecem nos rankings comerciais.

Exemplo:
    python prospector.py --categoria filmes --pais PT --max 2000 --validar
    python prospector.py --categoria adulto --pais ES --keywords "peliculas xxx" --validar
    python prospector.py --seeds Alvos2.txt --fontes links,mirrors,crtsh --max 5000

Dependencias: requests, beautifulsoup4, dnspython  (ja instaladas no .venv)
"""

import os, re, sys, csv, glob, gzip, json, time, random, socket, argparse, base64, hashlib
import threading
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

try:
    import dns.resolver
    TEM_DNS = True
except Exception:
    TEM_DNS = False

requests.packages.urllib3.disable_warnings()

BASE = os.path.dirname(os.path.abspath(__file__))
DIR_CACHE = os.path.join(BASE, ".cache")
DIR_OUT = os.path.join(BASE, "resultados")
FICH_VISTOS = os.path.join(DIR_OUT, "_ja_vistos.txt")
FICH_CONFIG = os.path.join(BASE, "config.json")
os.makedirs(DIR_CACHE, exist_ok=True)
os.makedirs(DIR_OUT, exist_ok=True)

LOCK = threading.Lock()

# =============================================================================
# 1. CONSTANTES / DICIONARIOS
# =============================================================================

UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# Paises -> idioma principal, ccTLD, moeda, parametros de motor de busca
PAISES = {
    "PT": {"lang": "pt", "tld": ".pt", "moeda": "€", "ddg": "pt-pt", "bing": "pt-PT", "nome": ["portugal", "português", "portugues"]},
    "BR": {"lang": "br", "tld": ".com.br", "moeda": "R$", "ddg": "br-pt", "bing": "pt-BR", "nome": ["brasil", "brazil"]},
    "ES": {"lang": "es", "tld": ".es", "moeda": "€", "ddg": "es-es", "bing": "es-ES", "nome": ["españa", "espana"]},
    "MX": {"lang": "es", "tld": ".mx", "moeda": "$", "ddg": "mx-es", "bing": "es-MX", "nome": ["méxico", "mexico"]},
    "AR": {"lang": "es", "tld": ".com.ar", "moeda": "$", "ddg": "ar-es", "bing": "es-AR", "nome": ["argentina"]},
    "US": {"lang": "en", "tld": ".us", "moeda": "$", "ddg": "us-en", "bing": "en-US", "nome": ["usa", "united states"]},
    "UK": {"lang": "en", "tld": ".co.uk", "moeda": "£", "ddg": "uk-en", "bing": "en-GB", "nome": ["united kingdom", "britain"]},
    "FR": {"lang": "fr", "tld": ".fr", "moeda": "€", "ddg": "fr-fr", "bing": "fr-FR", "nome": ["france"]},
    "DE": {"lang": "de", "tld": ".de", "moeda": "€", "ddg": "de-de", "bing": "de-DE", "nome": ["deutschland", "germany"]},
    "IT": {"lang": "it", "tld": ".it", "moeda": "€", "ddg": "it-it", "bing": "it-IT", "nome": ["italia"]},
    "NL": {"lang": "nl", "tld": ".nl", "moeda": "€", "ddg": "nl-nl", "bing": "nl-NL", "nome": ["nederland"]},
    "PL": {"lang": "pl", "tld": ".pl", "moeda": "zł", "ddg": "pl-pl", "bing": "pl-PL", "nome": ["polska", "poland"]},
    "TR": {"lang": "tr", "tld": ".com.tr", "moeda": "₺", "ddg": "tr-tr", "bing": "tr-TR", "nome": ["türkiye", "turkiye"]},
    "RU": {"lang": "ru", "tld": ".ru", "moeda": "₽", "ddg": "ru-ru", "bing": "ru-RU", "nome": ["россия", "russia"]},
    "ID": {"lang": "id", "tld": ".id", "moeda": "Rp", "ddg": "id-id", "bing": "id-ID", "nome": ["indonesia"]},
    "IN": {"lang": "en", "tld": ".in", "moeda": "₹", "ddg": "in-en", "bing": "en-IN", "nome": ["india"]},
    "VN": {"lang": "vi", "tld": ".vn", "moeda": "₫", "ddg": "vn-vi", "bing": "vi-VN", "nome": ["viet nam", "vietnam"]},
    "TH": {"lang": "th", "tld": ".th", "moeda": "฿", "ddg": "th-th", "bing": "th-TH", "nome": ["thailand", "ไทย"]},
    "RO": {"lang": "ro", "tld": ".ro", "moeda": "lei", "ddg": "ro-ro", "bing": "ro-RO", "nome": ["romania", "românia"]},
    "GR": {"lang": "el", "tld": ".gr", "moeda": "€", "ddg": "gr-el", "bing": "el-GR", "nome": ["ελλάδα", "greece"]},
    "EG": {"lang": "ar", "tld": ".eg", "moeda": "ج.م", "ddg": "eg-ar", "bing": "ar-EG", "nome": ["مصر", "egypt"]},
    "SA": {"lang": "ar", "tld": ".sa", "moeda": "﷼", "ddg": "xa-ar", "bing": "ar-SA", "nome": ["السعودية"]},
    "ZA": {"lang": "en", "tld": ".co.za", "moeda": "R", "ddg": "za-en", "bing": "en-ZA", "nome": ["south africa", "suid-afrika"]},
    # --- África ---
    "NG": {"lang": "en", "tld": ".com.ng", "moeda": "₦", "ddg": "ng-en", "bing": "en-NG", "nome": ["nigeria"]},
    "KE": {"lang": "en", "tld": ".co.ke", "moeda": "KSh", "ddg": "ke-en", "bing": "en-KE", "nome": ["kenya"]},
    "MA": {"lang": "fr", "tld": ".ma", "moeda": "د.م.", "ddg": "ma-fr", "bing": "fr-MA", "nome": ["maroc", "المغرب"]},
    "DZ": {"lang": "ar", "tld": ".dz", "moeda": "د.ج", "ddg": "dz-ar", "bing": "ar-DZ", "nome": ["الجزائر", "algerie"]},
    # --- Ásia ---
    "PH": {"lang": "en", "tld": ".ph", "moeda": "₱", "ddg": "ph-en", "bing": "en-PH", "nome": ["philippines", "pinoy"]},
    "MY": {"lang": "ms", "tld": ".com.my", "moeda": "RM", "ddg": "my-ms", "bing": "ms-MY", "nome": ["malaysia"]},
    "PK": {"lang": "en", "tld": ".pk", "moeda": "₨", "ddg": "pk-en", "bing": "en-PK", "nome": ["pakistan"]},
    "BD": {"lang": "bn", "tld": ".com.bd", "moeda": "৳", "ddg": "bd-en", "bing": "bn-BD", "nome": ["bangladesh", "বাংলাদেশ"]},
    "JP": {"lang": "ja", "tld": ".jp", "moeda": "¥", "ddg": "jp-jp", "bing": "ja-JP", "nome": ["日本"]},
    "KR": {"lang": "ko", "tld": ".kr", "moeda": "₩", "ddg": "kr-kr", "bing": "ko-KR", "nome": ["한국"]},
    "TW": {"lang": "zh", "tld": ".tw", "moeda": "NT$", "ddg": "tw-tzh", "bing": "zh-TW", "nome": ["台灣"]},
    # --- Europa ---
    "UA": {"lang": "uk", "tld": ".ua", "moeda": "₴", "ddg": "ua-uk", "bing": "uk-UA", "nome": ["україна"]},
    "CZ": {"lang": "cs", "tld": ".cz", "moeda": "Kč", "ddg": "cz-cs", "bing": "cs-CZ", "nome": ["česko", "cesko"]},
    "HU": {"lang": "hu", "tld": ".hu", "moeda": "Ft", "ddg": "hu-hu", "bing": "hu-HU", "nome": ["magyarország"]},
    "SE": {"lang": "sv", "tld": ".se", "moeda": "kr", "ddg": "se-sv", "bing": "sv-SE", "nome": ["sverige"]},
    "BE": {"lang": "nl", "tld": ".be", "moeda": "€", "ddg": "be-nl", "bing": "nl-BE", "nome": ["belgië", "belgique"]},
    "AT": {"lang": "de", "tld": ".at", "moeda": "€", "ddg": "at-de", "bing": "de-AT", "nome": ["österreich"]},
    "CH": {"lang": "de", "tld": ".ch", "moeda": "CHF", "ddg": "ch-de", "bing": "de-CH", "nome": ["schweiz", "suisse"]},
    "IE": {"lang": "en", "tld": ".ie", "moeda": "€", "ddg": "ie-en", "bing": "en-IE", "nome": ["ireland", "éire"]},
    # --- Américas ---
    "CA": {"lang": "en", "tld": ".ca", "moeda": "$", "ddg": "ca-en", "bing": "en-CA", "nome": ["canada"]},
    "CL": {"lang": "es", "tld": ".cl", "moeda": "$", "ddg": "cl-es", "bing": "es-CL", "nome": ["chile"]},
    "CO": {"lang": "es", "tld": ".com.co", "moeda": "$", "ddg": "co-es", "bing": "es-CO", "nome": ["colombia"]},
    "PE": {"lang": "es", "tld": ".pe", "moeda": "S/", "ddg": "pe-es", "bing": "es-PE", "nome": ["perú", "peru"]},
    "GLOBAL": {"lang": "en", "tld": "", "moeda": "$", "ddg": "wt-wt", "bing": "en-US", "nome": []},
}

# Lexico por idioma: verbos de consumo + modificadores comerciais
LEXICO = {
    "en": {"v": ["watch", "stream", "download"], "m": ["online free", "free", "hd", "full", "no sign up", "english subtitles", "2026"], "site": ["best sites to watch", "free site"]},
    "pt": {"v": ["ver", "assistir"], "m": ["online grátis", "grátis", "hd", "legendado", "completo", "sem registo", "português"], "site": ["melhores sites para ver", "site para ver"]},
    "br": {"v": ["assistir", "ver"], "m": ["online grátis", "dublado", "legendado", "hd", "completo", "sem cadastro"], "site": ["melhores sites para assistir", "site para assistir"]},
    "es": {"v": ["ver", "descargar"], "m": ["online gratis", "gratis", "hd", "castellano", "latino", "completa", "sin registro"], "site": ["mejores paginas para ver", "pagina para ver"]},
    "fr": {"v": ["voir", "regarder", "télécharger"], "m": ["en streaming gratuit", "gratuit", "vf", "vostfr", "hd", "complet"], "site": ["meilleurs sites pour regarder", "site de streaming"]},
    "de": {"v": ["anschauen", "streamen", "herunterladen"], "m": ["kostenlos online", "kostenlos", "deutsch", "hd", "ohne anmeldung"], "site": ["beste seiten um", "streaming seite"]},
    "it": {"v": ["guardare", "vedere", "scaricare"], "m": ["online gratis", "gratis", "streaming ita", "hd", "senza registrazione"], "site": ["migliori siti per vedere", "sito streaming"]},
    "nl": {"v": ["kijken", "streamen"], "m": ["online gratis", "gratis", "nederlands", "hd"], "site": ["beste sites om te kijken"]},
    "pl": {"v": ["oglądaj", "obejrzeć", "pobierz"], "m": ["online za darmo", "za darmo", "lektor pl", "napisy pl", "hd"], "site": ["najlepsze strony do oglądania"]},
    "tr": {"v": ["izle", "indir"], "m": ["online ücretsiz", "ücretsiz", "türkçe dublaj", "altyazılı", "full hd"], "site": ["izleme siteleri"]},
    "ru": {"v": ["смотреть", "скачать"], "m": ["онлайн бесплатно", "бесплатно", "в хорошем качестве", "без регистрации"], "site": ["лучшие сайты для просмотра"]},
    "id": {"v": ["nonton", "download"], "m": ["online gratis", "gratis", "sub indo", "full movie", "hd"], "site": ["situs nonton"]},
    "vi": {"v": ["xem", "tải"], "m": ["online miễn phí", "miễn phí", "vietsub", "thuyết minh", "hd"], "site": ["trang web xem"]},
    "th": {"v": ["ดู", "โหลด"], "m": ["ออนไลน์ ฟรี", "ฟรี", "พากย์ไทย", "ซับไทย"], "site": ["เว็บดู"]},
    "ro": {"v": ["vezi", "descarca"], "m": ["online gratis", "gratis", "subtitrat in romana", "hd"], "site": ["cele mai bune site-uri"]},
    "el": {"v": ["δες", "παρακολούθηση"], "m": ["online δωρεάν", "δωρεάν", "με ελληνικούς υπότιτλους"], "site": ["καλύτερες σελίδες"]},
    "ar": {"v": ["مشاهدة", "تحميل"], "m": ["اون لاين مجانا", "مجانا", "مترجم", "بجودة عالية"], "site": ["مواقع مشاهدة"]},
    "ms": {"v": ["tonton", "muat turun"], "m": ["online percuma", "percuma", "sarikata melayu", "hd", "penuh"], "site": ["laman web tonton"]},
    "bn": {"v": ["দেখুন", "ডাউনলোড"], "m": ["অনলাইন ফ্রি", "ফ্রি", "বাংলা সাবটাইটেল", "এইচডি"], "site": ["দেখার ওয়েবসাইট"]},
    "ja": {"v": ["無料視聴", "ダウンロード"], "m": ["無料", "オンライン", "日本語字幕", "フル", "高画質"], "site": ["無料視聴サイト"]},
    "ko": {"v": ["보기", "다시보기", "다운로드"], "m": ["무료", "온라인", "자막", "고화질", "링크"], "site": ["무료 사이트"]},
    "zh": {"v": ["線上看", "下載"], "m": ["免費", "線上", "中文字幕", "高清", "完整版"], "site": ["免費線上看網站"]},
    "uk": {"v": ["дивитися", "завантажити"], "m": ["онлайн безкоштовно", "безкоштовно", "українською", "в хорошій якості"], "site": ["сайти для перегляду"]},
    "cs": {"v": ["sledovat", "stáhnout"], "m": ["online zdarma", "zdarma", "s titulky", "cz dabing", "hd"], "site": ["nejlepší stránky"]},
    "hu": {"v": ["nézni", "letöltés"], "m": ["online ingyen", "ingyen", "magyarul", "teljes film", "hd"], "site": ["online néző oldalak"]},
    "sv": {"v": ["se", "ladda ner"], "m": ["online gratis", "gratis", "svensk text", "hd"], "site": ["bästa sajter"]},
}

# Substantivos por categoria e idioma
NOMES = {
    "filmes": {
        "ms": ["filem"], "bn": ["মুভি", "সিনেমা"], "ja": ["映画"], "ko": ["영화"], "zh": ["電影"], "uk": ["фільми"], "cs": ["filmy"], "hu": ["filmek"], "sv": ["filmer"],
        "en": ["movies", "films"], "pt": ["filmes"], "br": ["filmes"], "es": ["peliculas", "películas"],
        "fr": ["films"], "de": ["filme"], "it": ["film"], "nl": ["films"], "pl": ["filmy"],
        "tr": ["film"], "ru": ["фильмы"], "id": ["film"], "vi": ["phim"], "th": ["หนัง"],
        "ro": ["filme"], "el": ["ταινίες"], "ar": ["افلام"],
    },
    "series": {
        "ms": ["siri", "drama"], "bn": ["সিরিজ"], "ja": ["ドラマ", "海外ドラマ"], "ko": ["드라마"], "zh": ["影集", "電視劇"], "uk": ["серіали"], "cs": ["seriály"], "hu": ["sorozatok"], "sv": ["serier"],
        "en": ["tv series", "tv shows"], "pt": ["séries", "series"], "br": ["séries"], "es": ["series"],
        "fr": ["séries"], "de": ["serien"], "it": ["serie tv"], "nl": ["series"], "pl": ["seriale"],
        "tr": ["dizi"], "ru": ["сериалы"], "id": ["drama", "serial"], "vi": ["phim bộ"], "th": ["ซีรีย์"],
        "ro": ["seriale"], "el": ["σειρές"], "ar": ["مسلسلات"],
    },
    "anime": {
        "ms": ["anime"], "bn": ["এনিমে"], "ja": ["アニメ"], "ko": ["애니"], "zh": ["動漫"], "uk": ["аніме"], "cs": ["anime"], "hu": ["anime"], "sv": ["anime"],
        "en": ["anime"], "pt": ["anime", "animes"], "br": ["animes"], "es": ["anime"], "fr": ["anime"],
        "de": ["anime"], "it": ["anime"], "nl": ["anime"], "pl": ["anime"], "tr": ["anime"],
        "ru": ["аниме"], "id": ["anime"], "vi": ["anime"], "th": ["อนิเมะ"], "ro": ["anime"],
        "el": ["anime"], "ar": ["انمي"],
    },
    "manga": {
        "bn": ["মাঙ্গা"], "el": ["manga"], "nl": ["manga"], "pl": ["manga"], "ro": ["manga"], "th": ["มังงะ"],
        "ms": ["komik"], "ja": ["漫画"], "ko": ["웹툰", "만화"], "zh": ["漫畫"], "uk": ["манга"], "cs": ["manga"], "hu": ["manga"], "sv": ["manga"],
        "en": ["manga", "webtoon", "comics"], "pt": ["manga", "mangá"], "br": ["mangá"], "es": ["manga"],
        "fr": ["manga", "scan"], "de": ["manga"], "it": ["manga"], "id": ["manga", "komik"],
        "tr": ["manga"], "ru": ["манга"], "vi": ["truyện tranh"], "ar": ["مانجا"],
    },
    "desporto": {
        "ms": ["bola sepak langsung"], "bn": ["খেলা সরাসরি"], "ja": ["スポーツ 生中継", "サッカー 無料"], "ko": ["스포츠 중계", "축구 중계"], "zh": ["體育直播", "足球直播"], "uk": ["футбол онлайн"], "cs": ["fotbal živě"], "hu": ["élő foci"], "sv": ["fotboll live"],
        "en": ["live football", "live sports", "nba live", "ufc live"], "pt": ["futebol em direto", "desporto em direto"],
        "br": ["futebol ao vivo", "jogos ao vivo"], "es": ["futbol en vivo", "deportes en directo"],
        "fr": ["football en direct", "sport en direct"], "de": ["fussball live", "sport live"],
        "it": ["calcio streaming", "sport diretta"], "nl": ["voetbal live"], "pl": ["mecze na żywo"],
        "tr": ["maç izle", "canlı maç"], "ru": ["футбол онлайн"], "id": ["bola live", "streaming bola"],
        "vi": ["bóng đá trực tiếp"], "th": ["บอลสด"], "ro": ["meciuri live"], "el": ["ζωντανά ποδόσφαιρο"],
        "ar": ["مباريات بث مباشر"],
    },
    "adulto": {
        "ms": ["lucah"], "bn": ["সেক্স ভিডিও"], "ja": ["エロ動画", "無修正"], "ko": ["야동"], "zh": ["成人影片"], "uk": ["порно"], "cs": ["porno"], "hu": ["pornó"], "sv": ["porr"],
        "en": ["porn", "xxx", "sex videos"], "pt": ["porno", "videos porno"], "br": ["porno", "videos de sexo"],
        "es": ["porno", "videos xxx"], "fr": ["porno", "video x"], "de": ["porno", "pornos"],
        "it": ["porno", "video porno"], "nl": ["porno"], "pl": ["porno"], "tr": ["porno"],
        "ru": ["порно"], "id": ["bokep"], "vi": ["phim sex"], "th": ["หนังโป๊"], "ro": ["porno"],
        "el": ["πορνο"], "ar": ["سكس"],
    },
    "download": {
        "bn": ["ডাউনলোড"], "el": ["δωρεάν λήψη"], "nl": ["gratis downloaden"], "ro": ["descarca gratis"], "th": ["โหลดฟรี"],
        "ms": ["muat turun percuma"], "ja": ["ダウンロード 無料"], "ko": ["다운로드"], "zh": ["下載"], "uk": ["скачати безкоштовно"], "cs": ["stáhnout zdarma"], "hu": ["letöltés ingyen"], "sv": ["ladda ner gratis"],
        "en": ["torrent download", "free download", "direct download"], "pt": ["download grátis", "descarregar"],
        "br": ["download grátis", "baixar"], "es": ["descargar gratis", "descarga directa"],
        "fr": ["telecharger gratuit", "ddl"], "de": ["kostenlos herunterladen"], "it": ["scaricare gratis"],
        "pl": ["pobierz za darmo"], "tr": ["indir"], "ru": ["скачать бесплатно"], "id": ["download gratis"],
        "vi": ["tải miễn phí"], "ar": ["تحميل مجاني"],
    },
    "jogos": {
        "bn": ["গেম"], "el": ["δωρεάν παιχνίδια"], "nl": ["gratis online spelletjes"], "ro": ["jocuri online gratis"], "th": ["เกมออนไลน์ฟรี"], "vi": ["game online miễn phí"],
        "ms": ["permainan online"], "ja": ["無料ゲーム"], "ko": ["무료 게임"], "zh": ["免費遊戲"], "uk": ["ігри онлайн"], "cs": ["hry online"], "hu": ["online játékok"], "sv": ["spel online"],
        "en": ["free online games", "play games online"], "pt": ["jogos online grátis"], "br": ["jogos online grátis"],
        "es": ["juegos online gratis"], "fr": ["jeux en ligne gratuits"], "de": ["kostenlose online spiele"],
        "it": ["giochi online gratis"], "pl": ["gry online za darmo"], "tr": ["online oyun"],
        "ru": ["игры онлайн"], "id": ["game online gratis"], "ar": ["العاب اون لاين"],
    },
    "noticias": {
        "el": ["ειδήσεις"], "nl": ["nieuws"], "ro": ["stiri"], "th": ["ข่าว"], "vi": ["tin tức"],
        "ms": ["berita"], "bn": ["খবর"], "ja": ["ニュース"], "ko": ["뉴스"], "zh": ["新聞"], "uk": ["новини"], "cs": ["zprávy"], "hu": ["hírek"], "sv": ["nyheter"],
        "en": ["breaking news", "news portal"], "pt": ["notícias", "jornal online"], "br": ["notícias", "portal de notícias"],
        "es": ["noticias", "diario online"], "fr": ["actualités"], "de": ["nachrichten"], "it": ["notizie"],
        "pl": ["wiadomości"], "tr": ["haber"], "ru": ["новости"], "id": ["berita"], "ar": ["اخبار"],
    },
    "musica": {
        "bn": ["গান ডাউনলোড"], "el": ["δωρεάν μουσική"], "nl": ["muziek downloaden"], "pl": ["pobierz muzykę"], "ro": ["descarca muzica"], "th": ["โหลดเพลง"], "vi": ["tải nhạc"],
        "ms": ["muat turun lagu"], "ja": ["音楽 ダウンロード"], "ko": ["음악 다운"], "zh": ["音樂下載"], "uk": ["скачати музику"], "cs": ["stáhnout hudbu"], "hu": ["zene letöltés"], "sv": ["ladda ner musik"],
        "en": ["free mp3 download", "listen music online"], "pt": ["música grátis", "baixar música"],
        "br": ["baixar música grátis"], "es": ["descargar musica gratis"], "fr": ["telecharger musique"],
        "de": ["musik kostenlos"], "it": ["scaricare musica"], "tr": ["mp3 indir"], "ru": ["скачать музыку"],
        "id": ["download lagu"], "ar": ["تحميل اغاني"],
    },
    "software": {
        "bn": ["সফটওয্যার"], "el": ["δωρεάν προγράμματα"], "nl": ["gratis software"], "pl": ["programy do pobrania"], "ro": ["programe gratis"], "th": ["โหลดโปรแกรม"], "vi": ["tải phần mềm"],
        "ms": ["muat turun aplikasi"], "ja": ["ソフト ダウンロード"], "ko": ["프로그램 다운"], "zh": ["軟體下載"], "uk": ["скачати програми"], "cs": ["programy ke stažení"], "hu": ["program letöltés"], "sv": ["program gratis"],
        "en": ["free software download", "cracked apk", "mod apk"], "pt": ["programas grátis", "apk mod"],
        "br": ["programas grátis", "apk mod"], "es": ["programas gratis", "apk mod"],
        "fr": ["logiciel gratuit"], "de": ["software kostenlos"], "it": ["programmi gratis"],
        "tr": ["program indir"], "ru": ["скачать программы"], "id": ["download aplikasi"], "ar": ["تحميل برامج"],
    },
}

# "Footprints" - assinaturas de CMS/temas usados em massa por sites destes nichos.
# Pesquisar por estas frases devolve centenas de sites do mesmo tipo que nenhum
# ranking comercial lista.
FOOTPRINTS = {
    # "*" = assinaturas de CMS/tema, funcionam em qualquer idioma.
    # As restantes chaves sao por idioma: nao faz sentido procurar "assistir online"
    # no Japao nem "izle" na Suecia.
    "filmes": {
        "*": ['"Powered by DooPlay"', '"Powered by" "dooplay"', '"WP Theme" "cuevana"',
              '"video embed" "watch full movie" -netflix'],
        "pt": ['"WordPress" "assistir online" "temporada"', '"filmes online" "series online" sitemap',
               '"assistir filme completo" "dublado"'],
        "br": ['"assistir online" "dublado e legendado"', '"filmes online" "series online" sitemap'],
        "es": ['"ver online" "pelicula completa" "latino"', '"cuevana" clon'],
        "en": ['"watch online free" "full movie" "no sign up"'],
        "tr": ['"film izle" "full hd izle"'],
        "id": ['"nonton film" "sub indo" "lk21"'],
        "ru": ['"смотреть онлайн" "в хорошем качестве" "бесплатно"'],
        "ja": ['"無料動画" "フル"'],
        "ko": ['"다시보기" "무료보기"'],
        "zh": ['"線上看" "完整版"'],
    },
    "series": {
        "*": ['"Powered by DooPlay" series', '"episodes online" "season" watch free'],
        "pt": ['"episodios online" "temporada"'], "br": ['"assistir serie online" "episodios"'],
        "es": ['"ver serie online" "capitulos"'], "tr": ['"dizi izle" "bölüm"'],
        "ko": ['"드라마 다시보기"'],
    },
    "anime": {
        "*": ['"anime online" "episodes" "sub"', '"Powered by" "anime streaming"'],
        "pt": ['"animes online" "episódios" "legendado"'], "br": ['"animes online" "dublado"'],
        "es": ['"anime online" "sub español"'], "id": ['"anime" "sub indo" "batch"'],
        "ja": ['"アニメ" "無料視聴"'],
    },
    "manga": {
        "*": ['"Powered by Madara"', '"WP Manga" read online', '"read manga online" "chapter"'],
        "pt": ['"ler manga online" "capítulo"'], "es": ['"leer manga online" "capitulo"'],
        "id": ['"baca komik" "bahasa indonesia"'],
    },
    "desporto": {
        "*": ['"live stream" "kick off" watch free football', '"live streaming" "hd" football free'],
        "pt": ['"jogos ao vivo" "transmissão" futebol'], "br": ['"futebol ao vivo" "assistir online"'],
        "es": ['"ver futbol en vivo" "gratis"'], "tr": ['"canlı maç izle"'],
        "id": ['"live streaming bola" "gratis"'],
    },
    "adulto": {
        "*": ['"Powered by KVS"', '"kernel video sharing"', '"powered by mechbunny"',
              '"tube" "porn videos" "categories"'],
        "es": ['"videos porno" "gratis" "xxx"'], "id": ['"bokep" "video" "terbaru"'],
        "ja": ['"エロ動画" "無料"'], "ko": ['"야동" "무료"'],
    },
    "download": {
        "*": ['"index of" mkv', '"Powered by XFileSharing"', '"ddl" "uptobox" "1fichier"'],
        "pt": ['"baixar filmes" "torrent" "magnet"'], "br": ['"download" "dublado" "1080p" magnet"'],
        "ru": ['"скачать торрент" "бесплатно"'],
    },
    "jogos": {"*": ['"powered by" "html5 games" arcade', '"play free online games" "arcade"'],
              "pt": ['"jogar jogos online gratis"']},
    "noticias": {"*": ['"Powered by WordPress" "latest news"'],
                 "pt": ['"portal de noticias" "publicidade"']},
    "musica": {"*": ['"download mp3" "320kbps"', '"free mp3 download" "album"'],
               "pt": ['"baixar musica" "mp3" "gratis"']},
    "software": {"*": ['"apk download" "mod" "latest version"', '"crack" "serial" "download"'],
                 "pt": ['"baixar programas" "ativador"']},
}

# Dominios que nunca interessam (majors, CDNs, redes sociais, encurtadores, hosting)
BLACKLIST_EXATA = set("""
google.com google.pt google.es youtube.com youtu.be facebook.com fb.com instagram.com twitter.com x.com
tiktok.com netflix.com primevideo.com amazon.com amazon.es amazon.co.uk disneyplus.com hbomax.com max.com
hulu.com crunchyroll.com spotify.com apple.com itunes.apple.com microsoft.com live.com bing.com yahoo.com
wikipedia.org wikimedia.org imdb.com themoviedb.org reddit.com pinterest.com linkedin.com whatsapp.com
telegram.org t.me discord.com discord.gg twitch.tv dailymotion.com vimeo.com wordpress.com wordpress.org
blogger.com blogspot.com medium.com github.com gitlab.com stackoverflow.com quora.com tumblr.com
cloudflare.com cloudfront.net akamai.net akamaized.net jsdelivr.net googleapis.com gstatic.com
doubleclick.net googlesyndication.com google-analytics.com googletagmanager.com adservice.google.com
bit.ly tinyurl.com goo.gl t.co ow.ly cutt.ly shorturl.at linktr.ee
paypal.com stripe.com visa.com mastercard.com ebay.com aliexpress.com mercadolivre.com
justwatch.com plex.tv rottentomatoes.com metacritic.com letterboxd.com filmaffinity.com adorocinema.com
sensacine.com allocine.fr moviepilot.de mymovies.it filmweb.pl kinopoisk.ru
archive.org web.archive.org creativecommons.org mozilla.org w3.org schema.org gravatar.com
""".split())

BLACKLIST_SUB = [
    # free hosting / plataformas: enchem o crt.sh de ruido e nao sao publishers reais
    "pages.dev", "workers.dev", "web.app", "firebaseapp.com", "github.io", "gitlab.io",
    "onrender.com", "glitch.me", "repl.co", "replit.dev", "surge.sh", "000webhostapp.com",
    "neocities.org", "blogspot.", "tilda.ws", "webflow.io", "framer.website", "canva.site",
    "wp.com", "wixsite.com", "weebly.com", "squarespace.com", "shopify.com", "myshopify.com",
    "sites.google.com", "s3.amazonaws.com", "herokuapp.com", "netlify.app", "vercel.app",
    "cdn.", "static.", "img.", "api.", "mail.", "smtp.", "ftp.", "webmail.", "cpanel.",
    "gov.", "edu.", ".gov", ".edu", ".mil", "police.", ".int",
    "googleusercontent.com", "gstatic.com", "fbcdn.net", "twimg.com", "ytimg.com", "licdn.com",
]

TLD_MULTI = {
    "co.uk", "org.uk", "me.uk", "ac.uk", "com.br", "net.br", "org.br", "com.au", "net.au",
    "co.in", "com.mx", "com.ar", "com.tr", "co.za", "com.pl", "com.es", "co.jp", "co.kr",
    "com.pt", "com.co", "com.pe", "com.ve", "com.uy", "co.id", "co.th", "com.vn", "com.ua",
    "com.ng", "com.ph", "com.my", "com.sg", "com.hk", "com.tw", "com.eg", "com.sa", "com.pk",
    "com.bd", "com.gr", "com.cy", "org.il", "co.il", "net.in", "org.in",
}

# Prefixos tipicos de mirrors/clones (o teu Alvos2.txt esta cheio deles: ww1., ww4., ...)
PREFIXOS_MIRROR = ["", "www", "ww1", "ww2", "ww3", "ww4", "ww5", "ww6", "ww7", "ww8", "ww9",
                   "w1", "w2", "m", "new", "new1", "tv", "hd", "watch", "go", "play", "s1", "s2",
                   "beta", "old", "app", "site", "web", "movie", "film", "stream"]

TLDS_MIRROR = [".to", ".cc", ".com", ".net", ".org", ".io", ".me", ".tv", ".se", ".ru", ".in",
               ".ag", ".sx", ".is", ".li", ".lat", ".ws", ".pw", ".vip", ".cfd", ".sbs", ".icu",
               ".xyz", ".club", ".online", ".site", ".fun", ".life", ".pro", ".cyou", ".bond",
               ".mov", ".ink", ".gd", ".gs", ".ms", ".nu", ".st", ".cx", ".ch", ".pl", ".cz"]

# SSPs com sellers.json publico -> lista de dominios de publishers a monetizar
SELLERS_JSON = [
    # verificados a responder; os que falham sao simplesmente saltados
    "https://openx.com/sellers.json",
    "https://smartadserver.com/sellers.json",
    "https://www.rubiconproject.com/sellers.json",
    "https://www.criteo.com/sellers.json",
    "https://www.indexexchange.com/sellers.json",
    "https://appnexus.com/sellers.json",
    "https://www.triplelift.com/sellers.json",
    "https://www.adform.com/sellers.json",
    "https://sonobi.com/sellers.json",
    "https://gumgum.com/sellers.json",
    "https://sharethrough.com/sellers.json",
    "https://onetag.com/sellers.json",
    "https://improvedigital.com/sellers.json",
    "https://richaudience.com/sellers.json",
    "https://smaato.com/sellers.json",
    "https://loopme.com/sellers.json",
    "https://adyoulike.com/sellers.json",
    "https://media.net/sellers.json",
    "https://e-planning.net/sellers.json",
    "https://vidoomy.com/sellers.json",
    "https://www.epom.com/sellers.json",
    "https://www.eskimi.com/sellers.json",
    "https://www.mgid.com/sellers.json",
    "https://galaksion.com/sellers.json",
    # redes fortes em trafego "long tail" / adulto
    "https://juicyads.rocks/sellers.json",
    "https://adsterra.com/sellers.json",
    "https://pubmatic.com/sellers.json",
    "https://ap.lijit.com/sellers.json",
]

# Redes de publicidade detetaveis no HTML (sinal forte: o site ja monetiza)
REDES_ADS = {
    "adsense": ["pagead2.googlesyndication.com", "adsbygoogle"],
    "gam": ["securepubads.g.doubleclick.net", "googletagservices"],
    "prebid": ["prebid.js", "pbjs."],
    "exoclick": ["exoclick", "exdynsrv", "magsrv"],
    "juicyads": ["juicyads", "poweredby.jads"],
    "adsterra": ["adsterra", "highperformanceformat", "profitableratecpm", "displaycontentnetwork"],
    "propellerads": ["propellerads", "propeller", "onclickalgo", "onclkds"],
    "popads": ["popads.net", "popcash", "poperblock"],
    "hilltopads": ["hilltopads", "ak.ptrackrs"],
    "monetag": ["monetag", "dtscout"],
    "outbrain_taboola": ["outbrain", "taboola"],
    "mgid": ["mgid.com", "jsc.mgid"],
    "clickadu": ["clickadu", "clckads"],
    "trafficstars": ["trafficstars", "tsyndicate"],
    "media_net": ["contextual.media.net"],
}


# =============================================================================
# 2. UTILITARIOS
# =============================================================================

VERBOSE = True

def log(msg, nivel="."):
    if VERBOSE:
        with LOCK:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {nivel} {msg}", flush=True)


def headers(lang=None):
    h = {
        "User-Agent": random.choice(UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{lang},en;q=0.8" if lang else "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    return h


def _cache_path(url):
    return os.path.join(DIR_CACHE, hashlib.md5(url.encode()).hexdigest() + ".bin")


def http(url, timeout=25, lang=None, cache_horas=0, params=None, stream_max=None):
    """GET com cache opcional em disco. Devolve texto ou None."""
    chave = url + (json.dumps(params, sort_keys=True) if params else "")
    cp = _cache_path(chave)
    if cache_horas and os.path.exists(cp):
        if (time.time() - os.path.getmtime(cp)) < cache_horas * 3600:
            try:
                with gzip.open(cp, "rt", encoding="utf8") as f:
                    return f.read()
            except Exception:
                pass
    # timeout como tuplo (ligar, ler): um servidor que aceita a ligacao e depois
    # responde a conta-gotas nao pode prender a corrida indefinidamente
    tmo = timeout if isinstance(timeout, tuple) else (8, timeout)
    for tentativa in range(2):
        try:
            r = requests.get(url, params=params, headers=headers(lang), timeout=tmo,
                             verify=False, allow_redirects=True)
            if r.status_code == 200:
                txt = _corrigir_codificacao(r).text
                if stream_max:
                    txt = txt[:stream_max]
                if cache_horas:
                    try:
                        with gzip.open(cp, "wt", encoding="utf8") as f:
                            f.write(txt)
                    except Exception:
                        pass
                return txt
            if r.status_code in (429, 403):
                time.sleep(1.5)      # sem esperas longas: o motor esta bloqueado, insistir nao ajuda
                break
        except Exception:
            time.sleep(1.5)
    return None


def http_bytes(url, timeout=90, cache_horas=0):
    cp = _cache_path(url) + ".raw"
    if cache_horas and os.path.exists(cp) and (time.time() - os.path.getmtime(cp)) < cache_horas * 3600:
        return open(cp, "rb").read()
    try:
        r = requests.get(url, headers=headers(), timeout=timeout, verify=False)
        if r.status_code == 200:
            if cache_horas:
                open(cp, "wb").write(r.content)
            return r.content
    except Exception:
        pass
    return None


def _corrigir_codificacao(resp):
    """Sem charset no cabecalho, o requests assume ISO-8859-1 e estraga tudo o que
    nao for latino: japones, coreano, chines, russo, grego. Isso corrompia os
    titulos E as palavras-chave usadas no score."""
    ct = resp.headers.get("content-type", "").lower()
    if "charset" not in ct:
        detectada = None
        try:
            cabeca = resp.content[:4096].decode("ascii", "ignore").lower()
            m = re.search(r'charset=["\']?([a-z0-9\-_]+)', cabeca)
            if m:
                detectada = m.group(1)          # <meta charset=...> dentro do HTML
        except Exception:
            pass
        resp.encoding = detectada or resp.apparent_encoding or resp.encoding
    return resp


def normalizar_host(valor):
    """'HTTPS://WWW.Site.com/xpto?a=1' -> 'site.com'  (mantem subdominios reais)"""
    if not valor:
        return ""
    v = valor.strip().lower()
    v = re.sub(r"^\*\.", "", v)
    if "://" in v:
        v = urlparse(v).netloc
    else:
        v = v.split("/")[0]
    v = v.split("@")[-1].split(":")[0].strip(". ")
    if v.startswith("www."):
        v = v[4:]
    if not re.match(r"^[a-z0-9\.\-]+\.[a-z]{2,24}$", v):
        return ""
    if v.count(".") > 4 or len(v) > 80 or len(v) < 4:
        return ""
    return v


def dominio_raiz(host):
    """host -> dominio registavel (trata co.uk, com.br, ...)"""
    p = host.split(".")
    if len(p) <= 2:
        return host
    if ".".join(p[-2:]) in TLD_MULTI:
        return ".".join(p[-3:])
    return ".".join(p[-2:])


def marca_do_dominio(host):
    """'ww1.fmovies.to' -> 'fmovies'"""
    raiz = dominio_raiz(host)
    return raiz.split(".")[0]


MARCAS_BLOQUEADAS = {d.split(".")[0] for d in BLACKLIST_EXATA} | {
    "google", "youtube", "facebook", "instagram", "netflix", "amazon", "apple", "microsoft",
    "twitter", "tiktok", "whatsapp", "telegram", "paypal", "wikipedia", "bitcoin", "cloudflare"}


def esta_na_blacklist(host):
    raiz = dominio_raiz(host)
    if raiz in BLACKLIST_EXATA or host in BLACKLIST_EXATA:
        return True
    if marca_do_dominio(host) in MARCAS_BLOQUEADAS:
        return True
    for b in BLACKLIST_SUB:
        if b in host:
            return True
    if re.search(r"\.(gov|edu|mil|int)($|\.)", host):
        return True
    return False


def ler_lista(caminho):
    if not caminho or not os.path.exists(caminho):
        return set()
    out = set()
    with open(caminho, "r", encoding="utf8", errors="ignore") as f:
        for l in f:
            l = l.strip()
            if not l or l.startswith("#"):
                continue
            h = normalizar_host(l.split(",")[0].split(";")[0].split("\t")[0])
            if h:
                out.add(h)
    return out


_RESOLVER = None

def _resolver():
    global _RESOLVER
    if _RESOLVER is None:
        if TEM_DNS:
            r = dns.resolver.Resolver(configure=True)
            r.nameservers = ["1.1.1.1", "8.8.8.8", "9.9.9.9"] + list(r.nameservers)[:2]
            r.timeout, r.lifetime = 2.0, 2.5
            _RESOLVER = r
        else:
            _RESOLVER = False
    return _RESOLVER


def resolve(host):
    r = _resolver()
    if r:
        try:
            r.resolve(host, "A")
            return True
        except Exception:
            return False
    try:
        socket.setdefaulttimeout(3)
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


# =============================================================================
# 3. GERACAO DE QUERIES
# =============================================================================

def gerar_queries(categoria, pais, keywords, limite=40):
    """Constroi queries multi-idioma. Verbo, substantivo e modificador vem sempre
    do MESMO idioma (senao sai lixo tipo 'ver movies hd')."""
    cfg = PAISES.get(pais.upper(), PAISES["GLOBAL"])
    lang = cfg["lang"]

    # pares (idioma, substantivo): idioma do pais + ingles (funciona em todo o lado)
    pares = []
    if categoria and categoria in NOMES:
        for l in dict.fromkeys([lang, "en"]):
            for n in NOMES[categoria].get(l, []):
                pares.append((l, n, True))
    # Palavras-chave do utilizador: entram no idioma do pais E em ingles. Se ele
    # escreveu "watch anime" com pais=PT, colar-lhe "ver ... grátis" dava
    # "ver watch anime grátis" - frase de lingua nenhuma. Assim ha sempre metade
    # das queries coerentes, escreva ele na lingua que escrever.
    for k in keywords:
        k = k.strip()
        if k:
            # uma palavra solta e um substantivo: vale a pena decorar com verbos
            # e modificadores. Uma frase feita ("watch anime", "assistir gratis")
            # ja traz verbo e modificador - decorar so produz disparates tipo
            # "stream free anime free".
            decorar = len(k.split()) == 1
            for l in dict.fromkeys([lang, "en"]):
                pares.append((l, k, decorar))
    # dedupe insensivel a maiusculas: "Anime" e "anime" sao a mesma pesquisa
    vistos, unicos = set(), []
    for l, n, dec in pares:
        chave = (l, n.lower())
        if chave not in vistos:
            vistos.add(chave)
            unicos.append((l, n.lower(), dec))
    pares = unicos
    if not pares:
        return []

    qs = []
    for l, nome, decorar in pares:
        lex = LEXICO.get(l, LEXICO["en"])
        qs.append(nome)
        if decorar:
            for v in lex["v"][:2]:
                for m in lex["m"][:4]:
                    qs.append(f"{v} {nome} {m}")
            for m in lex["m"][:3]:
                qs.append(f"{nome} {m}")
            for s in lex["site"][:2]:
                qs.append(f"{s} {nome}")
        # operadores que empurram o long tail para a superficie
        if cfg["tld"]:
            qs.append(f"{nome} site:{cfg['tld']}")
        qs.append(f'intitle:"{nome}" -site:youtube.com -site:netflix.com')
        for pal in cfg["nome"][:1]:
            qs.append(f"{nome} {pal}")

    # footprints de CMS: a mina de ouro para encontrar clones do mesmo nicho.
    # Os genericos ("*") valem em todo o lado; os outros so no idioma do pais.
    fps = FOOTPRINTS.get(categoria, {})
    for fp in list(fps.get("*", [])) + list(fps.get(lang, [])):
        qs.append(fp)
        if cfg["tld"]:
            qs.append(f"{fp} site:{cfg['tld']}")

    qs = list(dict.fromkeys(qs))
    random.shuffle(qs)
    return qs[:limite]


# =============================================================================
# 4. FONTES DE DESCOBERTA
# =============================================================================

def _extrair_dominios_html(html, ignorar=("duckduckgo", "bing.com", "microsoft", "msn.com",
                                          "mojeek", "startpage", "yahoo", "ecosia", "qwant")):
    out = set()
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.startswith("//duckduckgo.com/l/?") or "uddg=" in h:
            try:
                h = unquote(parse_qs(urlparse("https:" + h if h.startswith("//") else h).query).get("uddg", [""])[0])
            except Exception:
                continue
        if h.startswith("/url?q="):
            h = unquote(parse_qs(urlparse(h).query).get("q", [""])[0])
        if not h.startswith("http"):
            continue
        d = normalizar_host(h)
        if d and not any(i in d for i in ignorar):
            out.add(d)
    # Bing esconde os links em base64 (u=a1<base64>)
    for m in re.findall(r"u=a1([A-Za-z0-9_\-]{16,})", html):
        try:
            u = base64.urlsafe_b64decode(m + "=" * (-len(m) % 4)).decode("utf8", "ignore")
            if u.startswith("http"):
                d = normalizar_host(u)
                if d and not any(i in d for i in ignorar):
                    out.add(d)
        except Exception:
            pass
    return out


# Motores de busca. O estado e o que eu observei a testar de um IP residencial:
#   fiavel   -> devolve resultados de forma consistente
#   instavel -> responde as vezes; leva captcha ou 429 com frequencia
#   api      -> precisa de chave em config.json (nao ha scraping que resolva)
MOTORES = {
    "bing":        {"estado": "fiavel",   "tipo": "html"},
    "duckduckgo":  {"estado": "fiavel",   "tipo": "html"},
    "ddg-lite":    {"estado": "instavel", "tipo": "html"},
    "brave":       {"estado": "instavel", "tipo": "html"},
    "mojeek":      {"estado": "instavel", "tipo": "html"},
    "startpage":   {"estado": "instavel", "tipo": "html"},
    "yandex":      {"estado": "instavel", "tipo": "html"},
    "marginalia":  {"estado": "instavel", "tipo": "html"},
    "google-api":  {"estado": "api",      "tipo": "api", "chave": "google_cse"},
    "serper":      {"estado": "api",      "tipo": "api", "chave": "serper_api_key"},
}
MOTORES_DEFEITO = ["bing", "duckduckgo"]


FICH_CHAVES = os.path.join(BASE, "chaves.json")


def carregar_config():
    """config.json (versionado) para definicoes; chaves.json e variaveis de
    ambiente para segredos. O config.json esta no repositorio publico: uma chave
    la dentro fica publicada, por isso NAO se leem chaves de la."""
    conf = {}
    for fich in (FICH_CONFIG, FICH_CHAVES):
        if os.path.exists(fich):
            try:
                with open(fich, encoding="utf8") as f:
                    conf.update(json.load(f))
            except Exception as e:
                log(f"{os.path.basename(fich)} ilegível ({e}); a ignorar", "!")
    # ambiente ganha a tudo (e como a Streamlit Cloud passa os secrets)
    if os.environ.get("SERPER_API_KEY"):
        conf["serper_api_key"] = os.environ["SERPER_API_KEY"]
    if os.environ.get("GOOGLE_CSE_KEY") and os.environ.get("GOOGLE_CSE_CX"):
        conf["google_cse"] = {"key": os.environ["GOOGLE_CSE_KEY"],
                              "cx": os.environ["GOOGLE_CSE_CX"]}
    return conf


def _pedido_motor(motor, q, cfg, pag):
    """Devolve (url, params) para os motores de HTML."""
    lg = cfg["bing"].split("-")[0]
    if motor == "bing":
        return ("https://www.bing.com/search",
                {"q": q, "count": 30, "first": pag * 30 + 1, "setlang": lg})
    if motor == "duckduckgo":
        return ("https://html.duckduckgo.com/html/", {"q": q, "kl": cfg["ddg"], "s": pag * 30})
    if motor == "ddg-lite":
        return ("https://lite.duckduckgo.com/lite/", {"q": q, "kl": cfg["ddg"], "s": pag * 30})
    if motor == "brave":
        return ("https://search.brave.com/search", {"q": q, "offset": pag})
    if motor == "mojeek":
        return ("https://www.mojeek.com/search", {"q": q, "s": pag * 10})
    if motor == "startpage":
        return ("https://www.startpage.com/sp/search", {"query": q, "page": pag + 1})
    if motor == "yandex":
        return ("https://yandex.com/search/", {"text": q, "p": pag})
    if motor == "marginalia":
        return ("https://search.marginalia.nu/search", {"query": q, "page": pag + 1})
    return None


def _busca_api(motor, q, cfg, pag, conf):
    """Google a serio so por API oficial: a pagina de resultados do google.com
    e uma casca JavaScript, nao ha HTML para ler."""
    out = set()
    if motor == "serper":
        chave = conf.get("serper_api_key", "")
        if not chave:
            return out, "sem chave: põe SERPER_API_KEY no ambiente ou em chaves.json"
        try:
            r = requests.post("https://google.serper.dev/search",
                              headers={"X-API-KEY": chave, "Content-Type": "application/json"},
                              json={"q": q, "gl": cfg.get("gl", "pt"), "num": 100, "page": pag + 1},
                              timeout=25)
            if r.status_code != 200:
                return out, f"HTTP {r.status_code}"
            for item in r.json().get("organic", []):
                d = normalizar_host(item.get("link", ""))
                if d:
                    out.add(d)
        except Exception as e:
            return out, type(e).__name__
        return out, None
    if motor == "google-api":
        c = conf.get("google_cse") or {}
        if not (c.get("key") and c.get("cx")):
            return out, "sem chave: põe GOOGLE_CSE_KEY/GOOGLE_CSE_CX no ambiente ou em chaves.json"
        try:
            r = requests.get("https://www.googleapis.com/customsearch/v1",
                             params={"key": c["key"], "cx": c["cx"], "q": q,
                                     "num": 10, "start": pag * 10 + 1},
                             timeout=25)
            if r.status_code != 200:
                return out, f"HTTP {r.status_code}"
            for item in r.json().get("items", []):
                d = normalizar_host(item.get("link", ""))
                if d:
                    out.add(d)
        except Exception as e:
            return out, type(e).__name__
        return out, None
    return out, "motor desconhecido"


def fonte_busca(queries, pais, paginas=3, pausa=(1.5, 4.0), motores=None, max_api=90):
    """Pesquisa nos motores escolhidos, com paginacao e localizacao por pais.

    Os motores correm em paralelo (um lento nao segura os outros) e cada um tem
    disjuntor: ao fim de 3 respostas vazias seguidas sai da corrida. Sem isto,
    um motor a devolver captcha custava mais de um minuto por query, sempre.
    """
    cfg = PAISES.get(pais.upper(), PAISES["GLOBAL"])
    conf = carregar_config()
    motores = [m for m in (motores or MOTORES_DEFEITO) if m in MOTORES]
    if not motores:
        motores = list(MOTORES_DEFEITO)
    achados = {}
    por_motor = {m: 0 for m in motores}
    falhas = {m: 0 for m in motores}
    mortos = {}
    # Travao de quota: cada pagina de um motor por API e uma chamada paga/contada.
    # O Google da 100/dia gratis e o defeito 40 queries x 3 paginas sao 120 chamadas
    # - sem isto, a primeira corrida esgotava o dia (ou comecava a custar dinheiro).
    gastas_api = [0]

    def _um_motor(motor, q, pag):
        if MOTORES[motor]["tipo"] == "api":
            if gastas_api[0] >= max_api:
                return motor, set(), f"travão de quota: {max_api} chamadas gastas"
            gastas_api[0] += 1
            novos, erro = _busca_api(motor, q, cfg, pag, conf)
            return motor, novos, erro
        pedido = _pedido_motor(motor, q, cfg, pag)
        if not pedido:
            return motor, set(), "sem pedido"
        html = http(pedido[0], lang=cfg["bing"], params=pedido[1], cache_horas=12, timeout=(8, 15))
        return motor, _extrair_dominios_html(html), (None if html else "sem resposta")

    for q in queries:
        for pag in range(paginas):
            activos = [m for m in motores if m not in mortos]
            if not activos:
                log("busca: todos os motores desligados", "!")
                return achados
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=len(activos)) as ex:
                futs = [ex.submit(_um_motor, m, q, pag) for m in activos]
                for f in as_completed(futs):
                    try:
                        motor, novos, erro = f.result()
                    except Exception:
                        continue
                    if erro and MOTORES[motor]["tipo"] == "api":
                        mortos[motor] = erro
                        log(f"{motor}: {erro} — desligado", "!")
                        continue
                    antes = len(achados)
                    for d in novos:
                        achados.setdefault(d, f"busca:{motor}")
                    ganho = len(achados) - antes
                    por_motor[motor] += ganho
                    falhas[motor] = 0 if novos else falhas[motor] + 1
                    if falhas[motor] >= 3:
                        mortos[motor] = "3 respostas vazias seguidas (captcha/bloqueio)"
                        log(f"{motor}: desligado — {mortos[motor]}", "!")
            time.sleep(random.uniform(*pausa))
        log(f"busca: '{q[:42]}' ({time.time()-t0:.0f}s) -> {len(achados)} acumulados  "
            + " ".join(f"{m}={por_motor[m]}" for m in motores))

    for m, razao in mortos.items():
        log(f"resumo: {m} não rendeu nada ({razao})", "!")
    if gastas_api[0]:
        log(f"chamadas a API pagas/contadas nesta corrida: {gastas_api[0]} (limite {max_api})")
    return achados


def fonte_crtsh(termos, limite_por_termo=4000, max_termos=12):
    """Certificate Transparency: todo o dominio com HTTPS deixa rasto aqui.
    Apanha mirrors e sites novos que nenhum indice tem."""
    achados = {}
    for t in list(dict.fromkeys(termos))[:max_termos]:
        t = re.sub(r"[^a-z0-9]", "", t.lower())
        if len(t) < 4:
            continue
        txt = http(f"https://crt.sh/?q=%25{t}%25&output=json", timeout=60, cache_horas=48)
        if not txt:
            log(f"crtsh: '{t}' sem resposta", "!")
            continue
        try:
            dados = json.loads(txt)
        except Exception:
            continue
        n0 = len(achados)
        for reg in dados[:limite_por_termo]:
            for nome in str(reg.get("name_value", "")).split("\n"):
                d = normalizar_host(nome)
                if d and not esta_na_blacklist(d):
                    achados.setdefault(d, "crtsh")
        log(f"crtsh: '{t}' -> +{len(achados)-n0} hosts novos (acumulado {len(achados)})")
        time.sleep(1.0)
    return achados


def fonte_links(seeds, profundidade=1, max_paginas=400, workers=12):
    """Grafo de links: estes sites linkam-se uns aos outros em massa.
    A melhor fonte para encontrar clones/mirrors do mesmo nicho."""
    achados = {}
    visitados = set()
    fila = list(seeds)
    for nivel in range(max(1, profundidade)):
        alvo = [d for d in fila if d not in visitados][:max_paginas]
        if not alvo:
            break
        log(f"links: nivel {nivel+1} -> a varrer {len(alvo)} sites")
        novos_nivel = set()

        def _um(dom):
            visitados.add(dom)
            saida = set()
            for esquema in ("https://", "http://"):
                html = http(esquema + dom, timeout=15, cache_horas=72)
                if html:
                    for d in _extrair_dominios_html(html, ignorar=()):
                        if d != dom and dominio_raiz(d) != dominio_raiz(dom):
                            saida.add(d)
                    break
            return saida

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_um, d): d for d in alvo}
            for f in as_completed(futs):
                try:
                    for d in f.result():
                        achados.setdefault(d, "links")
                        novos_nivel.add(d)
                except Exception:
                    pass
        fila = [d for d in novos_nivel if not esta_na_blacklist(d)]
        log(f"links: nivel {nivel+1} -> {len(achados)} dominios acumulados")
    return achados


def fonte_mirrors(seeds, workers=120, max_marcas=25, max_candidatos=40000, n_tlds=22):
    """Gera permutacoes de dominio (ww1.marca.to, marca2.cc, marcahd.sbs, ...) e testa DNS.
    Encontra mirrors vivos que NAO estao em nenhum indice publico.
    O espaco de procura e limitado de proposito: marcas x variantes x tlds x prefixos
    cresce muito depressa (ver --max-candidatos-mirror)."""
    marcas = list(dict.fromkeys([marca_do_dominio(s) for s in seeds]))
    marcas = [m for m in marcas if len(m) >= 4 and not m.isdigit()][:max_marcas]
    tlds = TLDS_MIRROR[:n_tlds]
    candidatos = set()
    for m in marcas:
        base = re.sub(r"\d+$", "", m)
        variantes = list(dict.fromkeys([m, base, base + "hd", base + "tv", base + "2", base + "free"]))
        for v in variantes:
            for tld in tlds:
                for pre in PREFIXOS_MIRROR[:12]:
                    candidatos.add(f"{pre}.{v}{tld}" if pre else f"{v}{tld}")
    candidatos = list(candidatos)
    random.shuffle(candidatos)
    candidatos = candidatos[:max_candidatos]
    log(f"mirrors: {len(marcas)} marcas -> {len(candidatos)} candidatos a testar por DNS")
    vivos = {}
    feitos = [0]

    def _t(h):
        ok = resolve(h)
        feitos[0] += 1
        if feitos[0] % 2500 == 0:
            log(f"mirrors: {feitos[0]}/{len(candidatos)} testados, {len(vivos)} vivos")
        return h if ok else None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(_t, c) for c in candidatos]):
            r = f.result()
            if r:
                vivos.setdefault(normalizar_host(r) or r, "mirrors")
    log(f"mirrors: {len(vivos)} hosts vivos")
    return vivos


def fonte_crux(pais, termos, limite=200000):
    """Chrome UX Report (dados reais de trafego do Chrome, por pais).
    Sites com trafego a serio que o SimilarWeb nao lista."""
    cc = pais.lower()[:2]
    if cc == "uk":
        cc = "gb"
    idx = http(f"https://api.github.com/repos/zakird/crux-top-lists/contents/data/country/{cc}",
               timeout=30, cache_horas=168)
    if not idx:
        log("crux: nao consegui listar o repo", "!")
        return {}
    try:
        fich = sorted([x["name"] for x in json.loads(idx) if x["name"].endswith(".csv.gz")])
    except Exception:
        return {}
    if not fich:
        return {}
    url = f"https://raw.githubusercontent.com/zakird/crux-top-lists/main/data/country/{cc}/{fich[-1]}"
    raw = http_bytes(url, cache_horas=168)
    if not raw:
        log("crux: download falhou", "!")
        return {}
    try:
        txt = gzip.decompress(raw).decode("utf8", "ignore")
    except Exception:
        return {}
    padroes = [re.sub(r"[^a-z0-9]", "", t.lower()) for t in termos]
    padroes = [p for p in padroes if len(p) >= 4]
    achados = {}
    for linha in txt.splitlines()[1:limite]:
        origem = linha.split(",")[0].strip('"')
        d = normalizar_host(origem)
        if not d:
            continue
        chato = re.sub(r"[^a-z0-9]", "", d)
        if not padroes or any(p in chato for p in padroes):
            achados[d] = "crux"
    log(f"crux[{cc}]: {len(achados)} dominios (de {len(txt.splitlines())} do pais)")
    return achados


def fonte_sellers(termos, limite_por_fonte=60000):
    """sellers.json das SSPs = lista publica de publishers que JA monetizam.
    Prospects perfeitos: tem trafego, tem ads, tem quem decida."""
    padroes = [re.sub(r"[^a-z0-9]", "", t.lower()) for t in termos]
    padroes = [p for p in padroes if len(p) >= 4]
    achados = {}
    for url in SELLERS_JSON:
        txt = http(url, timeout=90, cache_horas=168)
        if not txt:
            continue
        try:
            dados = json.loads(txt)
        except Exception:
            # alguns servem json gigante/partido: cai para regex
            dados = {"sellers": [{"domain": m} for m in re.findall(r'"domain"\s*:\s*"([^"]+)"', txt)]}
        n0 = len(achados)
        for s in (dados.get("sellers") or [])[:limite_por_fonte]:
            d = normalizar_host(str(s.get("domain") or ""))
            if not d:
                continue
            chato = re.sub(r"[^a-z0-9]", "", d)
            if not padroes or any(p in chato for p in padroes):
                achados.setdefault(d, "sellers")
        log(f"sellers: {urlparse(url).netloc} -> +{len(achados)-n0}")
    return achados


def fonte_commoncrawl(seeds, max_seeds=25):
    """Common Crawl: enumera todos os hosts vistos sob um dominio semente
    (apanha subdominios/mirrors historicos)."""
    colls = http("https://index.commoncrawl.org/collinfo.json", timeout=40, cache_horas=168)
    if not colls:
        return {}
    try:
        cid = json.loads(colls)[0]["id"]
    except Exception:
        return {}
    achados = {}
    for s in list(seeds)[:max_seeds]:
        raiz = dominio_raiz(s)
        txt = http(f"https://index.commoncrawl.org/{cid}-index",
                   params={"url": f"*.{raiz}", "output": "json", "limit": "800",
                           "fl": "url", "filter": "=status:200"},
                   timeout=120, cache_horas=168)
        if not txt:
            continue
        for linha in txt.splitlines():
            try:
                d = normalizar_host(json.loads(linha).get("url", ""))
            except Exception:
                continue
            if d:
                achados.setdefault(d, "commoncrawl")
        log(f"cc: {raiz} -> acumulado {len(achados)}")
        time.sleep(1.0)
    return achados


# =============================================================================
# 5. VALIDACAO E SCORING
# =============================================================================

# Paginas-porta em JS (fingerprint + redirect). Sao um sinal FORTE: quem poe um
# muro destes esta a monetizar trafego. O requests nunca passa dali - mas o teu
# robot usa Playwright, por isso estes dominios devem entrar na lista na mesma.
RE_GATEWAY = re.compile(r"(var\s+redirect_link|/js/fingerprint/|location\.replace\(|location\.href\s*=|"
                        r"http-equiv=[\"']refresh|__cf_chl|challenge-platform|just a moment)", re.I)

RE_LIXO = re.compile(r"(domain (is )?for sale|comprar este dom|this domain is parked|buy this domain|"
                     r"parkingcrew|sedoparking|afternic|dan\.com|godaddy.*parked|coming soon|"
                     r"under construction|site em constru|default web page|apache2 ubuntu)", re.I)


def analisar_site(host, termos, pais, timeout=14):
    """Abre o site, extrai sinais e devolve um dicionario com score 0-100."""
    cfg = PAISES.get(pais.upper(), PAISES["GLOBAL"])
    r = {"dominio": host, "vivo": 0, "http": 0, "titulo": "", "idioma": "", "score": 0,
         "kw_hits": 0, "pais_ok": 0, "ads_txt": 0, "redes": "", "tamanho": 0, "url_final": "", "nota": ""}
    html = None
    for esquema in ("https://", "http://"):
        try:
            resp = requests.get(esquema + host, headers=headers(cfg["lang"]), timeout=timeout,
                                verify=False, allow_redirects=True)
            r["http"] = resp.status_code
            r["url_final"] = resp.url
            if resp.status_code < 400 and resp.text:
                html = _corrigir_codificacao(resp).text
                break
        except Exception:
            continue
    if not html:
        return r
    r["vivo"] = 1
    r["tamanho"] = len(html)
    baixo = html.lower()

    soup = BeautifulSoup(html[:400000], "html.parser")
    r["titulo"] = (soup.title.get_text(strip=True)[:150] if soup.title else "")
    tag_html = soup.find("html")
    r["idioma"] = (tag_html.get("lang", "")[:8].lower() if tag_html else "")
    meta_desc = ""
    md = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if md:
        meta_desc = str(md.get("content", ""))[:300]
    texto = " ".join([r["titulo"], meta_desc, " ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])[:15])]).lower()
    corpo = soup.get_text(" ", strip=True)[:20000].lower()

    if len(corpo) < 400 and RE_GATEWAY.search(baixo):
        # nao da para ler o conteudo sem browser: marca e deixa passar com score
        # neutro-positivo, para o scraper Playwright decidir depois
        r["nota"] = "gateway-js"
        r["score"] = 42
        if any(m in baixo for marcas in REDES_ADS.values() for m in marcas):
            r["score"] += 8
        return r

    # Muitos dos melhores alvos sao SPAs: o texto vem por JS e o get_text() vem quase
    # vazio. So se marca como estacionado quando o HTML tambem e pobre.
    n_scripts = baixo.count("<script")
    parece_app = n_scripts >= 3 or len(html) > 25000
    if RE_LIXO.search(baixo[:5000]) or (len(corpo) < 200 and not parece_app):
        r["nota"] = "parked/vazio"
        return r
    if len(corpo) < 200:
        r["nota"] = "spa/js"

    # --- relevancia por palavras-chave (fronteira de palavra: 'ver' nao pode
    #     bater em 'verbos', 'filme' nao pode bater em 'filmenu') ---
    hits = 0
    for t in termos:
        t = t.lower().strip()
        if len(t) < 3:
            continue
        # usa o radical: 'filmes' apanha filme/filmes, 'movies' apanha movie/movies
        raiz_t = t[:-1] if (len(t) > 4 and t.endswith("s")) else t
        rx = re.compile(r"(?<![\w])" + re.escape(raiz_t) + r"[a-z]{0,3}(?![\w])", re.I)
        if rx.search(texto):
            hits += 3
        elif rx.search(corpo):
            hits += 1
        elif rx.search(baixo[:150000]):
            hits += 1   # SPA: a palavra so aparece no HTML/JS cru
    r["kw_hits"] = hits

    # --- sinais de pais ---
    p = 0
    if cfg["tld"] and host.endswith(cfg["tld"]):
        p += 3
    if cfg["lang"] and r["idioma"].startswith(cfg["lang"][:2]):
        p += 3
    if cfg["moeda"] and cfg["moeda"] in html:
        p += 1
    for nome in cfg["nome"]:
        if nome in corpo:
            p += 1
            break
    if f'hreflang="{cfg["lang"][:2]}' in baixo:
        p += 1
    r["pais_ok"] = p

    # --- monetizacao ---
    redes = [nome for nome, marcas in REDES_ADS.items() if any(m in baixo for m in marcas)]
    r["redes"] = ",".join(redes)
    try:
        ra = requests.get(f"https://{host}/ads.txt", headers=headers(), timeout=8, verify=False)
        if ra.status_code == 200 and "," in ra.text and len(ra.text) > 40 and "<html" not in ra.text[:200].lower():
            r["ads_txt"] = len([l for l in ra.text.splitlines() if "," in l and not l.strip().startswith("#")])
    except Exception:
        pass

    # --- score final ---
    s = 15
    s += min(hits * 4, 35)
    s += min(p * 4, 15)
    if r["ads_txt"]:
        s += 12 + (5 if r["ads_txt"] > 40 else 0)
    if redes:
        s += 10
    if r["tamanho"] > 40000:
        s += 5
    if r["http"] == 200:
        s += 3
    if r["nota"] == "spa/js" and hits:
        s += 8   # SPA: so da para ler o HTML cru, nao penalizar por isso
    # porta de relevancia: sem uma unica palavra-chave do nicho, o site nao serve
    if hits == 0:
        s = min(s, 22)
        r["nota"] = "fora do nicho"
    r["score"] = max(0, min(100, s))
    return r


def validar_lote(dominios, termos, pais, workers=25):
    res = []
    total = len(dominios)
    feitos = [0]

    def _um(d):
        try:
            return analisar_site(d, termos, pais)
        except Exception:
            return {"dominio": d, "vivo": 0, "score": 0, "nota": "erro"}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_um, d) for d in dominios]
        for f in as_completed(futs):
            r = f.result()
            feitos[0] += 1
            if feitos[0] % 25 == 0 or feitos[0] == total:
                log(f"validacao: {feitos[0]}/{total}")
            if r and r.get("vivo"):
                res.append(r)
    res.sort(key=lambda x: -x.get("score", 0))
    return res


# =============================================================================
# 6. PIPELINE
# =============================================================================

def carregar_exclusoes(extra_ficheiros, usar_historico=True):
    """Domínios a NÃO devolver: os que já contactaste.

    Esta ferramenta é independente do robot de emails. A única ligação entre as
    duas é esta lista de ficheiros, declarada em config.json -> "exclusoes".
    Aceita caminhos relativos a esta pasta e wildcards (ex: "../Alvos*.txt").
    Lista vazia = o prospector não toca em nada fora da sua própria pasta.
    """
    caminhos = []
    if os.path.exists(FICH_CONFIG):
        try:
            with open(FICH_CONFIG, encoding="utf8") as f:
                caminhos = json.load(f).get("exclusoes", []) or []
        except Exception as e:
            log(f"config.json ilegível ({e}); a ignorar", "!")
    caminhos += list(extra_ficheiros or [])

    excl = set()
    for padrao in caminhos:
        padrao = padrao.strip()
        if not padrao:
            continue
        p = padrao if os.path.isabs(padrao) else os.path.join(BASE, padrao)
        encontrados = glob.glob(p)
        if not encontrados:
            log(f"exclusões: '{padrao}' não encontrado", "!")
        for cam in encontrados:
            n = len(excl)
            excl |= ler_lista(cam)
            log(f"exclusões: {os.path.basename(cam)} -> +{len(excl)-n}")
    if usar_historico:
        n = len(excl)
        excl |= ler_lista(FICH_VISTOS)
        if len(excl) > n:
            log(f"exclusões: histórico próprio -> +{len(excl)-n}")
    if not excl:
        log("exclusões: nenhuma (não há lista de domínios já contactados)", "!")
    return excl


def correr(args):
    global VERBOSE
    VERBOSE = not args.quieto
    t0 = time.time()
    pais = args.pais.upper()
    categoria = (args.categoria or "").lower().strip()
    keywords = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]

    # termos usados para filtrar/pontuar (categoria + keywords, no idioma do pais e em EN)
    cfg = PAISES.get(pais, PAISES["GLOBAL"])
    termos = list(keywords)
    if categoria in NOMES:
        termos += NOMES[categoria].get(cfg["lang"], []) + NOMES[categoria].get("en", [])
    termos = list(dict.fromkeys([t for t in termos if t]))
    if not termos and not args.seeds:
        print("ERRO: precisas de --categoria e/ou --keywords (ou --seeds).")
        return 1

    seeds = set()
    for f in (args.seeds or "").split(","):
        if f.strip():
            seeds |= ler_lista(f.strip() if os.path.isabs(f.strip()) else os.path.join(BASE, f.strip()))
    log(f"arranque | categoria={categoria or '-'} pais={pais} termos={termos[:6]} seeds={len(seeds)}")

    fontes = [f.strip() for f in args.fontes.split(",") if f.strip()]
    achados = {}   # dominio -> fonte

    def juntar(d):
        for k, v in (d or {}).items():
            if k not in achados:
                achados[k] = v

    if "busca" in fontes:
        queries = gerar_queries(categoria, pais, keywords, limite=args.queries)
        log(f"queries geradas: {len(queries)}")
        juntar(fonte_busca(queries, pais, paginas=args.paginas,
                           motores=[m.strip() for m in args.motores.split(",") if m.strip()],
                           max_api=args.max_api))
    if "crtsh" in fontes:
        juntar(fonte_crtsh(termos + [marca_do_dominio(s) for s in list(seeds)[:15]]))
    if "crux" in fontes:
        juntar(fonte_crux(pais, termos))
    if "sellers" in fontes:
        juntar(fonte_sellers(termos))
    if "links" in fontes:
        base_links = set(seeds) | set(list(achados.keys())[:args.max_links_seed])
        if base_links:
            juntar(fonte_links(base_links, profundidade=args.profundidade, max_paginas=args.max_links_seed))
        else:
            log("links: sem sementes, saltado", "!")
    if "mirrors" in fontes:
        base_m = set(seeds) | set(list(achados.keys())[:60])
        if base_m:
            juntar(fonte_mirrors(base_m, max_candidatos=args.max_mirror, n_tlds=args.mirror_tlds))
    if "commoncrawl" in fontes:
        base_cc = set(seeds) | set(list(achados.keys())[:25])
        if base_cc:
            juntar(fonte_commoncrawl(base_cc))

    log(f"BRUTO: {len(achados)} hosts encontrados")

    # --- limpeza ---
    excl = carregar_exclusoes(args.excluir.split(",") if args.excluir else [], not args.repetir)
    excl_raiz = {dominio_raiz(d) for d in excl}
    limpos = {}
    for d, fonte in achados.items():
        if esta_na_blacklist(d):
            continue
        if d in excl or dominio_raiz(d) in excl_raiz:
            continue
        if args.tld_pais and cfg["tld"] and not d.endswith(cfg["tld"]):
            continue
        if args.excluir_regex and re.search(args.excluir_regex, d):
            continue
        chave = dominio_raiz(d) if args.nivel == "dominio" else d
        limpos.setdefault(chave, fonte)
    log(f"LIMPO: {len(limpos)} candidatos (blacklist/duplicados/ja contactados removidos)")

    lista = list(limpos.items())
    random.shuffle(lista)
    lista = lista[:args.max]

    # --- validacao ---
    slug = re.sub(r"[^a-z0-9]+", "-", f"{categoria or 'geral'}-{pais}").strip("-")
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    fich_txt = args.out or os.path.join(DIR_OUT, f"alvos_{slug}_{carimbo}.txt")
    fich_csv = args.out_csv or os.path.join(DIR_OUT, f"detalhe_{slug}_{carimbo}.csv")

    if args.validar:
        log(f"a validar {len(lista)} sites (abre cada homepage, le titulo/idioma/ads.txt)...")
        resultados = validar_lote([d for d, _ in lista], termos, pais, workers=args.workers)
        for r in resultados:
            r["fonte"] = limpos.get(r["dominio"], "")
        # o CSV guarda tudo o que esta vivo (para poderes rever/ajustar o corte);
        # o .txt so leva o que passa o score minimo
        finais = [r["dominio"] for r in resultados if r.get("score", 0) >= args.min_score]
    else:
        resultados = [{"dominio": d, "fonte": f, "score": "", "vivo": "", "titulo": "",
                       "idioma": "", "kw_hits": "", "pais_ok": "", "ads_txt": "", "redes": "",
                       "http": "", "tamanho": "", "url_final": "", "nota": ""} for d, f in lista]
        finais = [d for d, _ in lista]

    # --- gravar ---
    with open(fich_txt, "w", encoding="utf8") as f:
        f.write("\n".join(finais) + ("\n" if finais else ""))
    cols = ["dominio", "score", "fonte", "vivo", "http", "idioma", "kw_hits", "pais_ok",
            "ads_txt", "redes", "tamanho", "titulo", "url_final", "nota"]
    with open(fich_csv, "w", encoding="utf8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in resultados:
            w.writerow(r)
    if not args.repetir:
        with open(FICH_VISTOS, "a", encoding="utf8") as f:
            for d in limpos.keys():
                f.write(d + "\n")

    dt = int(time.time() - t0)
    print("\n" + "=" * 66)
    print(f"  RESULTADO  ({dt//60}m{dt%60}s)")
    print("=" * 66)
    print(f"  brutos encontrados : {len(achados)}")
    print(f"  candidatos limpos  : {len(limpos)}")
    print(f"  na lista final     : {len(finais)}")
    if args.validar and resultados:
        bons = [r for r in resultados if isinstance(r.get('score'), int) and r['score'] >= 60]
        com_ads = [r for r in resultados if r.get('ads_txt')]
        print(f"  vivos analisados   : {len(resultados)}")
        print(f"  score >= 60        : {len(bons)}")
        print(f"  com ads.txt        : {len(com_ads)}  (ja monetizam)")
        print("\n  TOP 15:")
        for r in resultados[:15]:
            print(f"   {str(r.get('score','')).rjust(3)}  {r['dominio'][:38].ljust(40)} {str(r.get('titulo',''))[:34]}")
    print(f"\n  -> LISTA PARA O ROBOT : {fich_txt}")
    print(f"  -> DETALHE (csv)      : {fich_csv}")
    print("=" * 66 + "\n")
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Prospector - encontra websites por categoria + pais + palavras-chave",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
exemplos:
  python prospector.py --categoria filmes --pais PT --max 800 --validar
  python prospector.py --categoria adulto --pais ES --keywords "peliculas xxx,videos" --validar
  python prospector.py --seeds Alvos2.txt --fontes links,mirrors,crtsh --max 3000 --validar
  python prospector.py --categoria desporto --pais BR --fontes busca,crtsh,crux --validar --min-score 55

categorias: """ + ", ".join(sorted(NOMES.keys())) + """
paises:     """ + ", ".join(sorted(PAISES.keys())))
    p.add_argument("--categoria", default="", help="filmes, series, anime, desporto, adulto, download, jogos, noticias, musica, software, manga")
    p.add_argument("--pais", default="GLOBAL", help="PT, BR, ES, FR, DE, IT, US, UK, TR, ID, ... ou GLOBAL")
    p.add_argument("--keywords", default="", help="palavras-chave extra separadas por virgula")
    p.add_argument("--seeds", default="", help="ficheiro(s) .txt com dominios semente (ex: Alvos2.txt)")
    p.add_argument("--fontes", default="busca,crtsh,links,mirrors",
                   help="busca,crtsh,crux,sellers,links,mirrors,commoncrawl")
    p.add_argument("--max", type=int, default=1500, help="maximo de dominios a processar/validar")
    p.add_argument("--validar", action="store_true", help="abre cada site, deteta idioma/ads/relevancia e da score")
    p.add_argument("--min-score", type=int, default=0, dest="min_score", help="score minimo para entrar na lista (com --validar)")
    p.add_argument("--nivel", default="host", choices=["host", "dominio"], help="host mantem ww1.x.com; dominio agrega na raiz")
    p.add_argument("--out", default="", help="caminho do .txt de saida")
    p.add_argument("--out-csv", default="", dest="out_csv", help="caminho do .csv de detalhe")
    p.add_argument("--excluir", default="", help="ficheiros .txt/.csv extra a excluir (aceita wildcards)")
    p.add_argument("--excluir-regex", default="", dest="excluir_regex", help="regex de dominios a descartar")
    p.add_argument("--tld-pais", action="store_true", dest="tld_pais", help="so aceita dominios com o ccTLD do pais")
    p.add_argument("--repetir", action="store_true", help="nao usar o historico _ja_vistos.txt")
    p.add_argument("--queries", type=int, default=40, help="numero de queries de pesquisa a gerar")
    p.add_argument("--paginas", type=int, default=3, help="paginas de resultados por query")
    p.add_argument("--max-api", type=int, default=90, dest="max_api",
                   help="travão: máximo de chamadas a motores por API numa corrida (Google dá 100/dia grátis)")
    p.add_argument("--motores", default=",".join(MOTORES_DEFEITO),
                   help="motores da fonte 'busca': " + ", ".join(f"{k} ({v['estado']})" for k, v in MOTORES.items()))
    p.add_argument("--profundidade", type=int, default=1, help="niveis do grafo de links")
    p.add_argument("--max-links-seed", type=int, default=300, dest="max_links_seed", help="sites a varrer por nivel no grafo de links")
    p.add_argument("--workers", type=int, default=25, help="threads na validacao")
    p.add_argument("--max-mirror", type=int, default=40000, dest="max_mirror", help="maximo de candidatos DNS na fonte mirrors")
    p.add_argument("--mirror-tlds", type=int, default=22, dest="mirror_tlds", help="quantos TLDs testar na fonte mirrors (max 51)")
    p.add_argument("--quieto", action="store_true")
    args = p.parse_args()
    try:
        return correr(args)
    except KeyboardInterrupt:
        print("\ninterrompido pelo utilizador.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
