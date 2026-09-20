import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
import time

TARGET_URL = "Zyof.fuck.com"
OUTPUT_DIR = "./Cloned"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_DEPTH = 3
TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s [ZCLONER] %(message)s')
logger = logging.getLogger(__name__)

def normalize_url(url):
    url = url.strip()

    if not url:
        return ""

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return url
    
class ZCloner:
    def __init__(self, target_url, output_dir):
        self.target_url = target_url
        self.base_domain = urlparse(target_url).netloc
        self.output_dir = Path(output_dir)
        self.visited_urls = set()
        self.assets_map = {}
        self.bot_data = []
        self.chromium_path = self._find_chromium()
        
    def _find_chromium(self):
        possible_paths = [
            '/data/data/com.termux/files/usr/bin/chromium-browser',
            '/data/data/com.termux/files/usr/bin/chromium',
            '/data/data/com.termux/files/usr/bin/google-chrome',
            '/data/data/com.termux/files/usr/bin/google-chrome-stable',
        ]
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"[BROWSER] Chromium encontrado em: {path}")
                return path
        try:
            result = subprocess.run(['which', 'chromium-browser'], capture_output=True, text=True)
            if result.returncode == 0:
                path = result.stdout.strip()
                if path:
                    return path
        except:
            pass
        logger.error("[ERRO] Chromium não encontrado. Execute: pkg install chromium")
        return None

    def get_page_content(self, url):
        if not self.chromium_path:
            return None
        try:
            cmd = [
                self.chromium_path, '--headless', '--no-sandbox', '--disable-gpu',
                '--disable-dev-shm-usage', '--disable-software-rasterizer',
                '--disable-blink-features=AutomationControlled',
                '--user-agent=' + USER_AGENT, '--window-size=1920,1080',
                '--virtual-time-budget=10000', '--dump-dom', url
            ]
            logger.info(f"[NAV] Obtendo conteúdo de: {url}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
            if result.returncode == 0 and result.stdout:
                return result.stdout
            else:
                logger.error(f"[ERRO] Chromium retornou código {result.returncode}")
                if result.stderr:
                    logger.error(f"[ERRO] Detalhes: {result.stderr[:500]}")
                return None
        except subprocess.TimeoutExpired:
            logger.error(f"[TIMEOUT] Tempo excedido ao carregar: {url}")
            return None
        except Exception as e:
            logger.error(f"[ERRO] Falha ao obter página {url}: {e}")
            return None
            
    def get_local_path(self, url):
        parsed = urlparse(url)

        domain = parsed.netloc.lower()
        domain = domain.split("@")[-1]
        domain = domain.split(":")[0]

        path = parsed.path or "/index.html"

        if path.endswith("/"):
            path += "index.html"

        if not path.endswith(".html") and "." not in path.split("/")[-1]:
            path += ".html"

        filename = path.split("?")[0]

        return self.output_dir / domain / filename.lstrip("/")
    def download_asset(self, url, referer=None):
        if url in self.assets_map:
            return self.assets_map[url]
        try:
            headers = {'Referer': referer or self.target_url, 'User-Agent': USER_AGENT}
            response = requests.get(url, headers=headers, timeout=10, verify=False)
            if response.status_code == 200:
                local_path = self.get_local_path(url)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                self.assets_map[url] = str(local_path.relative_to(self.output_dir))
                logger.info(f"[ASSET] Baixado: {url}")
                return self.assets_map[url]
        except Exception as e:
            logger.warning(f"[ERRO] Falha ao baixar asset {url}: {e}")
        return None

    def process_page(self, url, depth=0):
        if url in self.visited_urls or depth > MAX_DEPTH:
            return
        self.visited_urls.add(url)
        logger.info(f"[PROCESS] Processando: {url} (Depth: {depth})")
        html_content = self.get_page_content(url)
        if not html_content:
            try:
                response = requests.get(url, headers={'User-Agent': USER_AGENT}, verify=False, timeout=10)
                html_content = response.text
                logger.info(f"[FALLBACK] Usando requests para: {url}")
            except:
                logger.error(f"[FALHA] Não foi possível obter conteúdo de: {url}")
                return
        soup = BeautifulSoup(html_content, 'html.parser')
        bot_entry = {"url": url, "title": soup.title.string if soup.title else "No Title", "forms": [], "links": [], "scripts": [], "styles": []}
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(url, href)
            if urlparse(full_url).netloc == self.base_domain:
                bot_entry["links"].append(full_url)
                if depth < MAX_DEPTH:
                    self.process_page(full_url, depth + 1)
        for form in soup.find_all('form'):
            action = form.get('action', '')
            method = form.get('method', 'GET').upper()
            inputs = []
            for inp in form.find_all(['input', 'textarea', 'select']):
                inputs.append({"name": inp.get('name'), "type": inp.get('type', 'text'), "required": inp.has_attr('required')})
            bot_entry["forms"].append({"action": urljoin(url, action), "method": method, "inputs": inputs})
        for link_tag in soup.find_all('link', rel='stylesheet'):
            href = link_tag.get('href')
            if href:
                local_css = self.download_asset(urljoin(url, href), url)
                if local_css:
                    link_tag['href'] = local_css
        for script_tag in soup.find_all('script', src=True):
            src = script_tag['src']
            local_js = self.download_asset(urljoin(url, src), url)
            if local_js:
                script_tag['src'] = local_js
            else:
                bot_entry["scripts"].append(src)
        for img_tag in soup.find_all('img', src=True):
            src = img_tag['src']
            local_img = self.download_asset(urljoin(url, src), url)
            if local_img:
                img_tag['src'] = local_img
        local_html_path = self.get_local_path(url)
        local_html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_html_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
        self.bot_data.append(bot_entry)
        logger.info(f"[SAVE] Página salva em: {local_html_path}")
        time.sleep(1)

    def run(self):
        logger.info(f"[INICIO] Clonagem iniciada para: {self.target_url}")
        logger.info(f"[INFO] Chromium: {self.chromium_path or 'Não encontrado - usando requests'}")
        self.output_dir.mkdir(exist_ok=True)
        try:
            self.process_page(self.target_url)
            bot_file = self.output_dir / "bot_data.json"
            with open(bot_file, 'w', encoding='utf-8') as f:
                json.dump(self.bot_data, f, indent=4, ensure_ascii=False)
            logger.info(f"[BOT] Dados estruturados salvos em: {bot_file}")
            logger.info("[FIM] Clonagem concluída.")
        except KeyboardInterrupt:
            logger.info("[INTERRUPT] Processo interrompido pelo usuário")
        except Exception as e:
            logger.error(f"[ERRO CRÍTICO] {e}")


RESET = "\033[0m"
BOLD = "\033[1m"
PURPLE = "\033[35m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
DIM = "\033[2m"
CLEAR = "\033[2J\033[H"


def color(text, tone=MAGENTA, bold=False):
    prefix = BOLD if bold else ""
    return f"{prefix}{tone}{text}{RESET}"


def clear_screen():
    print(CLEAR, end="")


def banner():
    print(color(r"""
 ███████╗ ██████╗██╗      ██████╗ ███╗   ██╗███████╗██████╗
 ╚══███╔╝██╔════╝██║     ██╔═══██╗████╗  ██║██╔════╝██╔══██╗
   ███╔╝ ██║     ██║     ██║   ██║██╔██╗ ██║█████╗  ██████╔╝
  ███╔╝  ██║     ██║     ██║   ██║██║╚██╗██║██╔══╝  ██╔══██╗
 ███████╗╚██████╗███████╗╚██████╔╝██║ ╚████║███████╗██║  ██║
 ╚══════╝ ╚═════╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝
""", PURPLE, True))
    print(color("                 [ Zcloner]", MAGENTA))
    print()


def pause():
    input(color("\n[ENTER] retornar ao menu...", DIM))


def loading():
    frames = ["[■□□□□□□□□□]", "[■■□□□□□□□□]", "[■■■□□□□□□□]", "[■■■■□□□□□□]", "[■■■■■□□□□□]", "[■■■■■■□□□□]", "[■■■■■■■□□□]", "[■■■■■■■■□□]", "[■■■■■■■■■□]", "[■■■■■■■■■■]"]
    print(color("\n[BOOT] preparando sequência de clonagem", CYAN))
    for frame in frames:
        print(f"\r{color(frame, MAGENTA)} {color('acessando alvo...', DIM)}", end="", flush=True)
        time.sleep(0.08)
    print(color("\n[BOOT] canal pronto.\n", MAGENTA))


def show_settings():
    print(color("\n╔════════════ CONFIGURAÇÕES ════════════╗", PURPLE, True))
    print(f"{color('URL alvo', MAGENTA, True)}       : {TARGET_URL}")
    print(f"{color('Diretório', MAGENTA, True)}      : {OUTPUT_DIR}")
    print(f"{color('Profundidade', MAGENTA, True)}    : {MAX_DEPTH}")
    print(f"{color('Timeout', MAGENTA, True)}         : {TIMEOUT}s")
    print(f"{color('User-Agent', MAGENTA, True)}      : {USER_AGENT}")
    print(color("╚═══════════════════════════════════════╝", PURPLE, True))


def settings_menu():
    global TARGET_URL, OUTPUT_DIR, MAX_DEPTH, TIMEOUT, USER_AGENT
    while True:
        clear_screen()
        banner()
        show_settings()
        print(color("\n[1] Alterar URL alvo", MAGENTA))
        print(color("[2] Alterar diretório de saída", MAGENTA))
        print(color("[3] Alterar profundidade máxima", MAGENTA))
        print(color("[4] Alterar timeout", MAGENTA))
        print(color("[5] Alterar user-agent", MAGENTA))
        print(color("[0] Voltar", WHITE))
        choice = input(color("\nconfig:// selecione uma opção: ", CYAN)).strip()
        try:
            if choice == "1":
                value = input("Nova URL alvo: ").strip()
                if value:
                    TARGET_URL = value
            elif choice == "2":
                value = input("Novo diretório: ").strip()
                if value:
                    OUTPUT_DIR = value
            elif choice == "3":
                value = input("Nova profundidade máxima: ").strip()
                if value:
                    MAX_DEPTH = max(0, int(value))
            elif choice == "4":
                value = input("Novo timeout em segundos: ").strip()
                if value:
                    TIMEOUT = max(1, int(value))
            elif choice == "5":
                value = input("Novo user-agent: ").strip()
                if value:
                    USER_AGENT = value
            elif choice == "0":
                return
            else:
                print(color("Opção inválida.", MAGENTA))
                time.sleep(0.8)
        except ValueError:
            print(color("Valor inválido; nenhuma alteração foi aplicada.", MAGENTA))
            time.sleep(1.2)


def show_report():
    report = Path(OUTPUT_DIR) / "bot_data.json"
    clear_screen()
    banner()
    print(color("ÚLTIMO RELATÓRIO", PURPLE, True))
    if not report.exists():
        print(color(f"\nNenhum relatório encontrado em: {report}", MAGENTA))
        pause()
        return
    try:
        with open(report, "r", encoding="utf-8") as file:
            data = json.load(file)
        print(color(f"\nArquivo: {report}\n", CYAN))
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(color(f"Falha ao ler o relatório: {exc}", MAGENTA))
    pause()


def start_clone():
    global TARGET_URL

    clear_screen()
    banner()

    entered_url = input(
        color(f"URL alvo [{TARGET_URL}]: ", CYAN)
    ).strip()

    if entered_url:
        TARGET_URL = normalize_url(entered_url)

    TARGET_URL = normalize_url(TARGET_URL)

    if not TARGET_URL:
        print(color("URL alvo não pode ficar vazia.", MAGENTA))
        pause()
        return

    print(color("\nResumo da operação", PURPLE, True))
    print(f"URL: {TARGET_URL}")
    print(f"Saída: {OUTPUT_DIR}")
    print(f"Profundidade: {MAX_DEPTH} | Timeout: {TIMEOUT}s")

    confirm = input(
        color("\nConfirmar clonagem? [s/N]: ", CYAN)
    ).strip().lower()

    if confirm not in ("s", "sim", "y", "yes"):
        print(color("Operação cancelada.", MAGENTA))
        pause()
        return

    loading()

    cloner = ZCloner(TARGET_URL, OUTPUT_DIR)
    cloner.run()

    print(color("\n╔════════════ RESUMO ════════════╗", PURPLE, True))
    print(
        f"{color('Páginas visitadas', MAGENTA, True)}: "
        f"{len(cloner.visited_urls)}"
    )
    print(
        f"{color('Assets baixados', MAGENTA, True)} : "
        f"{len(cloner.assets_map)}"
    )
    print(
        f"{color('Relatório', MAGENTA, True)}      : "
        f"{Path(OUTPUT_DIR) / 'bot_data.json'}"
    )
    print(color("╚════════════════════════════════╝", PURPLE, True))

    pause()


def about():
    clear_screen()
    banner()
    print(color("SOBRE", PURPLE, True))
    print("\nZCLONER pelo nome ja deve dizer sobre, e um clonador de sites basico em py")
    print(color("Criador: Zyof", MAGENTA, True))
    pause()


def main_menu():
    while True:
        clear_screen()
        banner()
        print(color("┌──────────────────────────────────────┐", PURPLE))
        print(color("│ [1] Iniciar clonagem                 │", MAGENTA))
        print(color("│ [2] Configurações                    │", MAGENTA))
        print(color("│ [3] Ver último relatório             │", MAGENTA))
        print(color("│ [4] Sobre                            │", MAGENTA))
        print(color("│ [0] Sair                             │", WHITE))
        print(color("└──────────────────────────────────────┘", PURPLE))
        choice = input(color("\nselecione uma opção: ", CYAN)).strip()
        if choice == "1":
            start_clone()
        elif choice == "2":
            settings_menu()
        elif choice == "3":
            show_report()
        elif choice == "4":
            about()
        elif choice == "0":
            print(color("\nEncerrando ZCLONER. Avalia aí krl.\n", MAGENTA, True))
            return
        else:
            print(color("Opção inválida.", MAGENTA))
            time.sleep(0.8)


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(color("\n\nSessão encerrada pelo usuário.\n", MAGENTA, True))
