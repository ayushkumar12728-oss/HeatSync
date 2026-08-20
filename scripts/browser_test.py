#!/usr/bin/env python3
"""
Headless-Chrome verification of the HeatSync 3D Digital Twin.

Starts the FastAPI backend (uvicorn, :8000) and the Vite dev server
(:5173) as subprocesses, drives a real headless Chrome session through the
main user flows, and reports pass/fail for each check together with any
browser console errors.

Run:  python scripts/browser_test.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from selenium.webdriver.common.by import By

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
FRONTEND = ROOT / "frontend"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def wait_for(cond, timeout: float, interval: float = 0.5, label: str = ""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = cond()
            if last:
                return last
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {label or cond} (last: {last!r})")


def _free_ports(ports=(8000, 5173)) -> None:
    """Kill stale listeners on the ports we need (Windows netstat/taskkill)."""
    import re
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=15).stdout
    except Exception:  # noqa: BLE001
        return
    pids = set()
    for line in out.splitlines():
        m = re.search(r":(8000|5173)\s+.*?LISTENING\s+(\d+)$", line.strip())
        if m and int(m.group(2)) not in pids:
            pids.add(int(m.group(2)))
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(1.0)


def main() -> int:
    servers: list[subprocess.Popen] = []
    _free_ports()

    # --- start backend ------------------------------------------------------ #
    print("== Starting FastAPI backend on :8000 ==")
    backend = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    servers.append(backend)

    # --- start frontend ----------------------------------------------------- #
    print("== Starting Vite dev server on :5173 ==")
    frontend = subprocess.Popen(
        "npx vite --host 127.0.0.1 --port 5173 --strictPort",
        cwd=str(FRONTEND),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    servers.append(frontend)

    exit_code = 1
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        opts = Options()
        opts.binary_location = "C:/Program Files/Google/Chrome/Application/chrome.exe"
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1600,950")
        opts.add_argument("--enable-webgl")
        opts.add_argument("--use-angle=swiftshader")
        opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})

        wait_for(lambda: _http_ok("http://127.0.0.1:8000/api/health"), 60, label="backend health")
        wait_for(lambda: _http_ok("http://127.0.0.1:5173/"), 60, label="vite up")
        print("== Both servers up ==")

        service = Service()
        driver = webdriver.Chrome(service=service, options=opts)
        try:
            console_errors: list[str] = []

            print("\n== 1. Initial page load ==")
            driver.get("http://127.0.0.1:5173/")
            wait_for(
                lambda: driver.find_elements(By.CSS_SELECTOR, ".city-search-input"),
                45, label="app shell mounted")
            time.sleep(5)

            canvases = driver.find_elements(By.CSS_SELECTOR, ".maplibregl-canvas")
            check("MapLibre canvas rendered", len(canvases) > 0, f"{len(canvases)} canvas(es)")

            check("App title HeatSync", _has_text(driver, "HeatSync"))
            search_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='Search any place']")
            check("Search box present", len(search_inputs) > 0,
                  "placeholder attr found" if search_inputs else "missing")

            # --- layers panel -------------------------------------------------- #
            print("\n== 2. Layer manager ==")
            time.sleep(1.0)
            check("Layer manager shows CITY section", _has_text(driver, "CITY"))
            check("Layer manager shows HEAT section", _has_text(driver, "HEAT"))
            check("Layer manager shows TERRAIN section", _has_text(driver, "TERRAIN"))
            check("Layer manager shows AIR QUALITY section", _has_text(driver, "AIR QUALITY"))
            check("Layer manager shows VEGETATION section", _has_text(driver, "VEGETATION"))
            check("Unavailable layers say UNAVAILABLE",
                  bool(driver.find_elements(By.CSS_SELECTOR, ".layer-unavail-badge")) or
                  _has_text(driver, "UNAVAILABLE"))
            # CITY group is open by default and should have 6 toggles
            toggles = driver.find_elements(By.CSS_SELECTOR, ".layer-toggle input")
            check("Layer toggles present", len(toggles) >= 6, f"{len(toggles)} toggles")
            # toggle the first available raster layer (e.g. NDVI) on + off
            for t in toggles:
                if t.is_displayed():
                    try:
                        t.click()
                        time.sleep(1.2)
                        break
                    except Exception:  # noqa: BLE001
                        continue

            # --- city intelligence --------------------------------------------- #
            print("\n== 3. City Intelligence ==")
            check("City Insights panel renders", _has_text(driver, "City Insights"))

            # --- hotspots ------------------------------------------------------- #
            print("\n== 4. Hotspot explorer ==")
            _click_text(driver, "Hotspots")
            time.sleep(2.5)
            check("Hotspot explorer opens",
                  _has_text(driver, "hottest") or _has_text(driver, "HOTSPOT") or _has_text(driver, "Top"))
            check("Hotspots show LST values", _has_text(driver, "°C"))

            # --- interventions -------------------------------------------------- #
            print("\n== 5. Cooling opportunity finder ==")
            _click_text(driver, "Interventions")
            time.sleep(2.5)
            check("Intervention finder opens",
                  _has_text(driver, "Cooling") or _has_text(driver, "intervention"))

            # --- map click ------------------------------------------------------ #
            print("\n== 6. Click map point ==")
            _click_text(driver, "City")  # back to city tab
            time.sleep(0.8)
            try:
                driver.find_element(By.CSS_SELECTOR, ".maplibregl-canvas")
                # Real user click: dispatch a mouse click at the map centre.
                driver.execute_script("""
                  const c = document.querySelector('.maplibregl-canvas');
                  const r = c.getBoundingClientRect();
                  const x = r.x + r.width * 0.55, y = r.y + r.height * 0.45;
                  const el = document.elementFromPoint(x, y) || c;
                  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
                """)
                wait_for(
                    lambda: driver.find_elements(By.CSS_SELECTOR, ".loc-panel"),
                    12, label="location panel")
                check("Location panel opens", bool(driver.find_elements(By.CSS_SELECTOR, ".loc-panel")))
                # wait for the profile fetch to render the ENVIRONMENT section
                wait_for(lambda: _has_text(driver, "ENVIRONMENT"), 12, label="environment data")
                check("Location shows environment data",
                      _has_text(driver, "ENVIRONMENT") and _has_text(driver, "°C"))
            except Exception as exc:  # noqa: BLE001
                check("Location panel opens", False, str(exc)[:160])

            # --- camera + time (map view still active) -------------------------- #
            print("\n== 7. Camera controls ==")
            for label in ("City", "District", "Street", "Orbit", "Reset"):
                _click_text(driver, label)
                time.sleep(0.5)
            cam_btns = driver.find_elements(By.CSS_SELECTOR, ".cam-btn")
            check("Camera preset buttons present", len(cam_btns) >= 5, f"{len(cam_btns)} buttons")

            print("\n== 8. Time machine ==")
            _click_text(driver, "Time")
            time.sleep(1.5)
            tm_ok = _has_text(driver, "Temporal thermal data unavailable") or \
                _has_text(driver, "TIME MACHINE")
            check("Time machine honest about data", tm_ok)

            # --- search --------------------------------------------------------- #
            print("\n== 9. Geocoding search ==")
            try:
                search_input = driver.find_element(
                    By.CSS_SELECTOR, "input[placeholder*='Search any place']")
                search_input.clear()
                search_input.send_keys("Khandagiri")
                wait_for(
                    lambda: driver.find_elements(By.CSS_SELECTOR, ".city-search-item"),
                    15, label="search results")
                results = driver.find_elements(By.CSS_SELECTOR, ".city-search-item")
                check("Nominatim results appear", len(results) > 0, f"{len(results)} results")
                if results:
                    results[0].click()
                    time.sleep(3.5)
                    check("Search flies to location + panel opens",
                          _has_text(driver, "LOCATION INTELLIGENCE") or _has_text(driver, "Selected"))
            except Exception as exc:  # noqa: BLE001
                check("Nominatim results appear", False, str(exc)[:200])

            # --- scenario ------------------------------------------------------- #
            print("\n== 10. Scenario mode ==")
            _click_text(driver, "Scenario")
            time.sleep(2.5)
            scenario_ok = (_has_text(driver, "SCENARIO") or _has_text(driver, "Scenario")) and \
                (_has_text(driver, "Green Cover") or _has_text(driver, "Increase") or
                 _has_text(driver, "Trees"))
            check("Scenario panel with interventions", scenario_ok)

            # --- analytics ------------------------------------------------------ #
            print("\n== 11. Analytics ==")
            _click_text(driver, "Analytics")
            time.sleep(3.0)
            check("Analytics shows data badges",
                  _has_text(driver, "REAL DATA") or _has_text(driver, "MODEL OUTPUT") or
                  _has_text(driver, "UNAVAILABLE"))
            check("No population in analytics", not _has_text(driver, "Population"))

            # --- AI ------------------------------------------------------------- #
            print("\n== 12. AI assistant ==")
            _click_text(driver, "AI Assistant")
            time.sleep(1.8)
            ai_ok = _has_text(driver, "Ask") or _has_text(driver, "Nemotron") or \
                _has_text(driver, "assistant")
            check("AI panel opens", ai_ok)

            # --- mobile layout -------------------------------------------------- #
            print("\n== 13. Responsive/mobile layout ==")
            driver.set_window_size(400, 800)
            time.sleep(2.5)
            horiz = driver.execute_script(
                "return document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("No horizontal overflow on mobile", horiz <= 0, f"overflow {horiz}px")
            # return to map view so the float buttons exist
            _click_text(driver, "3D Map")
            time.sleep(1.5)
            check("Mobile floating buttons present",
                  len(driver.find_elements(By.CSS_SELECTOR, ".map-float-btn")) > 0)
            driver.set_window_size(1600, 950)
            time.sleep(1.5)

            # --- console errors ------------------------------------------------ #
            print("\n== 14. Console ==")
            for entry in driver.get_log("browser"):
                if entry.get("level") in ("SEVERE", "ERROR"):
                    msg = entry.get("message", "")
                    if "404" in msg and ("tile" in msg.lower() or "404 (Not Found)" in msg):
                        continue
                    console_errors.append(msg[:300])
            check("No severe console errors", len(console_errors) == 0,
                  "; ".join(console_errors[:3]) or "clean")

        finally:
            driver.quit()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFATAL: {exc}", file=sys.stderr)
        exit_code = 2
    finally:
        for proc in servers:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1.0)
        for proc in servers:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    print("\n== SUMMARY ==")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    print(f"{passed}/{len(RESULTS)} checks passed")
    if exit_code == 2:
        return 2
    return 0 if passed == len(RESULTS) else 1


def _http_ok(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
            return resp.status < 400
    except Exception:  # noqa: BLE001
        return False


def _has_text(driver, text: str) -> bool:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text
        return text.lower() in body.lower()
    except Exception:  # noqa: BLE001
        return False


def _click_text(driver, text: str) -> bool:
    candidates = driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{text}']")
    for el in candidates:
        if el.is_displayed():
            try:
                el.click()
                return True
            except Exception:  # noqa: BLE001
                continue
    candidates = driver.find_elements(
        By.XPATH, f"//*[contains(normalize-space(text()),'{text}')]")
    for el in candidates:
        if el.is_displayed():
            try:
                el.click()
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


if __name__ == "__main__":
    raise SystemExit(main())
