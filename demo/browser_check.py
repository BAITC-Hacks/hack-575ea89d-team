"""Optional real-Firefox smoke check for the local demo (requires Selenium)."""
import argparse
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/demo/")
    parser.add_argument("--report", type=Path, default=Path("artifacts/report.json"))
    parser.add_argument("--screenshots", type=Path, default=Path("artifacts/browser"))
    args = parser.parse_args()
    report = args.report.resolve()
    if not report.is_file():
        parser.error(f"report file does not exist: {report}")
    args.screenshots.mkdir(parents=True, exist_ok=True)

    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(options=options)
    try:
        driver.set_window_size(1440, 1200)
        driver.get(args.url)
        wait = WebDriverWait(driver, 15)
        wait.until(lambda d: d.find_element("id", "campaign-rows").text.startswith("adaptive_1"))
        assert driver.find_element("id", "net").text.startswith("+")
        assert len(driver.find_elements("css selector", "#pilot-rows tr")) == 20
        assert len(driver.find_elements("css selector", "#campaign-rows tr")) == 10
        assert "visible" not in driver.find_element("id", "notice").get_attribute("class")
        driver.execute_script("""
          window.__demoErrors = [];
          window.addEventListener('error', e => window.__demoErrors.push(e.message));
          window.addEventListener('unhandledrejection', e => window.__demoErrors.push(String(e.reason)));
          const originalError = console.error.bind(console);
          console.error = (...args) => { window.__demoErrors.push(args.map(String).join(' ')); originalError(...args); };
        """)
        desktop = args.screenshots / "demo-desktop.png"
        driver.save_screenshot(str(desktop))

        driver.find_element("tag name", "body").click()
        ActionChains(driver).send_keys(Keys.TAB).send_keys(Keys.TAB).perform()
        active_id = driver.execute_script("return document.activeElement.id")
        assert active_id == "report-file", f"Tab order did not reach the JSON picker: {active_id!r}"
        focus_style = driver.execute_script(
            "return getComputedStyle(document.querySelector('.file-button')).outlineStyle"
        )
        assert focus_style != "none", "file picker has no visible keyboard focus"

        picker = driver.find_element("id", "report-file")
        picker.send_keys(str(report))
        wait.until(lambda d: d.find_element("id", "campaign-rows").text.startswith("adaptive_1"))
        assert len(driver.find_elements("css selector", "#pilot-rows tr")) == 20

        driver.set_window_size(390, 844)
        driver.execute_script("window.scrollTo(0, 0)")
        dimensions = driver.execute_script(
            "return {width: innerWidth, document: document.documentElement.clientWidth, "
            "scroll: document.documentElement.scrollWidth, table: "
            "document.querySelector('.table-wrap').clientWidth, tableScroll: "
            "document.querySelector('.table-wrap').scrollWidth}"
        )
        assert dimensions["scroll"] <= dimensions["document"], f"page overflows on mobile: {dimensions}"
        mobile = args.screenshots / "demo-mobile.png"
        driver.save_screenshot(str(mobile))

        picker.send_keys(str(Path("AGENTS.md").resolve()))
        wait.until(lambda d: "Не удалось открыть отчёт" in d.find_element("id", "notice").text)
        assert driver.find_element("id", "net").text == "—"

        console_errors = driver.execute_script("return window.__demoErrors")
        assert not console_errors, f"browser console errors: {console_errors}"
        print(f"Firefox {driver.capabilities.get('browserVersion')}: auto-load 20 pilots/10 campaigns PASS")
        print("keyboard tab/focus PASS; valid JSON upload PASS; damaged JSON clears old metrics PASS")
        print(f"mobile width PASS: {dimensions}")
        print(f"console errors: {len(console_errors)}")
        print(f"screenshots: {desktop}, {mobile}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
