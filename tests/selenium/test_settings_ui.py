"""Pruebas de interfaz (Selenium) de la ventana de configuración del cliente.

La página settings.html se abre en Chrome headless. El puente de Electron
(`window.solobino`, definido en preload.js) se reemplaza por un doble de prueba
que replica la validación de main.js -> saveConfig(), así la UI se prueba sin
abrir Electron ni guardar tokens reales.

Variables opcionales:
  SELENIUM_HEADLESS=0      ver el navegador mientras corre la prueba
  CHROMEDRIVER_PATH=...    usar un chromedriver concreto
  CHROMEDRIVER_ARGS=...    argumentos extra para chromedriver (separados por espacio)
"""
import json
import os
from pathlib import Path
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

SETTINGS = (Path(__file__).resolve().parents[2] / "desktop-ui" / "settings.html").as_uri()
SCREENSHOTS = Path(__file__).resolve().parents[2] / "reports" / "selenium"

# Doble de prueba de window.solobino. Las reglas de saveConfig copian las de main.js.
BRIDGE_MOCK = """
window.__saved = null;
window.__initialConfig = %s;
window.solobino = {
  getConfig: () => Promise.resolve(window.__initialConfig),
  saveConfig: (config) => new Promise((resolve, reject) => {
    try {
      const url = new URL(config.backendUrl);
      const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
      if ((url.protocol !== 'wss:' && !(local && url.protocol === 'ws:')) || !url.pathname.endsWith('/ws')) {
        throw new Error('Usa una URL wss://.../ws; ws:// solo se admite en este equipo.');
      }
      if (typeof config.token !== 'string' || !config.token.trim()) throw new Error('Falta el token del servicio.');
      window.__saved = config;
      resolve(true);
    } catch (e) { reject(e); }
  }),
};
"""


def build_driver():
    options = webdriver.ChromeOptions()
    if os.getenv("SELENIUM_HEADLESS", "1") != "0":
        options.add_argument("--headless=new")
    for arg in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=900,700"):
        options.add_argument(arg)
    if os.getenv("CHROME_BINARY"):
        options.binary_location = os.environ["CHROME_BINARY"]
    service = Service(
        executable_path=os.getenv("CHROMEDRIVER_PATH") or None,
        service_args=os.getenv("CHROMEDRIVER_ARGS", "").split() or None,
    )
    return webdriver.Chrome(options=options, service=service)


class SettingsWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = build_driver()
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def open_settings(self, initial=None):
        script = BRIDGE_MOCK % json.dumps(initial or {})
        self._mock = self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": script})["identifier"]
        self.driver.get(SETTINGS)
        self.wait = WebDriverWait(self.driver, 5)
        self.url = self.driver.find_element(By.ID, "backendUrl")
        self.token = self.driver.find_element(By.ID, "token")
        self.submit = self.driver.find_element(By.CSS_SELECTOR, "button[type=submit]")
        self.error = self.driver.find_element(By.ID, "error")

    def tearDown(self):
        self.driver.save_screenshot(str(SCREENSHOTS / f"{self._testMethodName}.png"))
        # Quita el doble inyectado para que la siguiente prueba parta de cero.
        self.driver.execute_cdp_cmd(
            "Page.removeScriptToEvaluateOnNewDocument", {"identifier": self._mock})
        self.driver.get("about:blank")

    def saved(self):
        return self.driver.execute_script("return window.__saved")

    def fill(self, url, token):
        self.url.clear()
        self.url.send_keys(url)
        self.token.clear()
        self.token.send_keys(token)
        self.submit.click()

    # --- Pruebas -----------------------------------------------------------

    def test_titulo_y_campos_visibles(self):
        self.open_settings()
        self.assertEqual(self.driver.title, "Conectar Solobino")
        self.assertTrue(self.url.is_displayed())
        self.assertTrue(self.token.is_displayed())
        self.assertEqual(self.token.get_attribute("type"), "password", "El token no debe verse en pantalla")

    def test_carga_configuracion_guardada(self):
        self.open_settings({"backendUrl": "wss://servidor.example/ws", "token": "abc"})
        self.wait.until(lambda d: self.url.get_attribute("value") != "")
        self.assertEqual(self.url.get_attribute("value"), "wss://servidor.example/ws")
        self.assertEqual(self.token.get_attribute("value"), "abc")

    def test_campos_obligatorios_impiden_enviar(self):
        self.open_settings()
        self.submit.click()
        self.assertFalse(self.driver.execute_script("return arguments[0].checkValidity()", self.url))
        self.assertIsNone(self.saved())

    def test_url_mal_formada_es_rechazada_por_el_formulario(self):
        self.open_settings()
        self.fill("esto-no-es-una-url", "token")
        self.assertFalse(self.driver.execute_script("return arguments[0].checkValidity()", self.url))
        self.assertIsNone(self.saved())

    def test_ws_remoto_inseguro_muestra_error(self):
        self.open_settings()
        self.fill("ws://192.168.1.50:8000/ws", "token")
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "error"), "wss://"))
        self.assertIsNone(self.saved())

    def test_ruta_distinta_de_ws_muestra_error(self):
        self.open_settings()
        self.fill("wss://servidor.example/api", "token")
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "error"), "wss://"))
        self.assertIsNone(self.saved())

    def test_token_solo_espacios_muestra_error(self):
        self.open_settings()
        self.fill("wss://servidor.example/ws", "   ")
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "error"), "token"))
        self.assertIsNone(self.saved())

    def test_ws_local_es_aceptado(self):
        self.open_settings()
        self.fill("ws://localhost:8000/ws", "sandbox-token")
        self.wait.until(lambda d: self.saved() is not None)
        self.assertEqual(self.saved()["backendUrl"], "ws://localhost:8000/ws")
        self.assertEqual(self.error.text, "")

    def test_wss_valido_se_guarda_sin_espacios(self):
        self.open_settings()
        self.fill("  wss://servidor.example/ws  ", "mi-token")
        self.wait.until(lambda d: self.saved() is not None)
        self.assertEqual(self.saved(), {"backendUrl": "wss://servidor.example/ws", "token": "mi-token"})


if __name__ == "__main__":
    unittest.main()
