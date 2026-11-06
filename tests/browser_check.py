"""Browser check: drive every flow of the running app in Chromium, like a user.

Covers what Streamlit's AppTest cannot: the custom components (prompt, command
blocks, command palette, history table), dialogs, keyboard shortcuts, the
streaming explanation, page navigation and the phone layout. Each step is
screenshotted, and every broken expectation is reported.

Usage, with the app running on port 8501 (started from a folder you do not
mind previewing in; the only commands run for real are read-only):

    uv run --with playwright python tests/browser_check.py screenshots/

Set CHROMIUM to a Chromium or headless-shell binary if Playwright's own browser
is not installed.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
EXE = os.environ.get("CHROMIUM")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
OUT.mkdir(parents=True, exist_ok=True)
problems: list[str] = []
errors: list[str] = []


def settle(page, extra: float = 1.0) -> None:
    time.sleep(0.5)
    try:
        page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=120000)
    except Exception:
        problems.append("the app never went idle")
    time.sleep(extra)


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"))
    for text in page.locator('[data-testid="stException"]').all_inner_texts():
        problems.append(f"[{name}] exception: {text[:300]}")
    print("step", name, flush=True)


def expect(condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


def send(page, text: str, mode: str = "ask") -> None:
    prompt = page.locator("input.in")
    current = page.locator("button.mode").inner_text().strip().lower()
    if current != mode:
        page.locator("button.mode").click()
    prompt.fill(text)
    prompt.press("Enter")
    settle(page, 2.5)


def focused_block(page):
    return page.locator("article.block.focused")


def block_action(page, label: str) -> None:
    focused_block(page).get_by_role("button", name=label).click()
    settle(page, 1.5)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=EXE) if EXE else p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1300})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text[:160]}") if m.type == "error" else None)
    page.goto(URL)
    page.wait_for_selector("input.in", timeout=120000)
    settle(page)
    shot(page, "01_empty_session")
    expect(page.locator("img.banner-art").count() == 1, "banner ghost missing")
    expect(page.locator(".statusbar").is_visible(), "status bar not visible")

    # An example request
    page.get_by_role("button", name="count the lines in every python file").click()
    settle(page, 3)
    expect(focused_block(page).count() == 1, "no focused block after the example")
    expect(page.locator("img.banner-art").count() == 0, "banner still shown with a result")
    shot(page, "02_example")

    # The explanation streams in and finishes
    page.wait_for_selector(".explain:not(.explain--wait):not(.explain--live)", timeout=60000)
    settle(page)
    shot(page, "03_explained")

    # Read-only run: runs straight from the block
    block_action(page, "▶ run")
    expect("✓ ran" in focused_block(page).inner_text(), "read-only command did not run from the block")
    expect(page.get_by_text("output", exact=True).count() >= 1, "no output pane after running")
    shot(page, "04_ran")

    # Prompt history: ArrowUp recalls the last request
    page.locator("input.in").press("ArrowUp")
    expect("python" in page.locator("input.in").input_value(), "ArrowUp did not recall the last request")
    page.locator("input.in").fill("")

    # Edit dialog shows the current command and checks a new version
    block_action(page, "✎ edit")
    dialog = page.get_by_role("dialog")
    current = focused_block(page).locator("code.cmd").inner_text()
    expect(dialog.locator("input").input_value().strip() == current.strip(), "edit dialog shows the wrong command")
    dialog.locator("input").fill("ls -la | head -5")
    dialog.get_by_role("button", name="Check").click()
    settle(page, 2)
    expect("edited" in focused_block(page).inner_text(), "edited marker missing")
    shot(page, "05_edited")

    # Explain mode with a dangerous command: dialog, typed confirmation
    send(page, "rm -rf *", mode="explain")
    expect("DANGEROUS" in focused_block(page).inner_text().upper(), "rm -rf * not rated dangerous")
    block_action(page, "▶ run")
    dialog = page.get_by_role("dialog")
    expect(dialog.count() == 1, "no confirmation dialog for a dangerous command")
    go = dialog.get_by_role("button", name="Run anyway")
    expect(go.is_disabled(), "Run anyway enabled before confirming")
    dialog.get_by_placeholder("run").fill("run")
    dialog.get_by_placeholder("run").press("Tab")
    time.sleep(1)
    expect(not dialog.get_by_role("button", name="Run anyway").is_disabled(), "typing run did not enable the button")
    shot(page, "06_danger_dialog")
    dialog.get_by_role("button", name="Cancel").click()
    settle(page)

    # A second dangerous command must not inherit the confirmation. Run is
    # clicked while the explanation is still streaming: the rerun that follows
    # its completion must not close the dialog.
    send(page, "rm -rf *.log", mode="explain")
    focused_block(page).get_by_role("button", name="▶ run").click()
    time.sleep(1.5)
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("button", name="Run anyway").is_disabled(), "CONFIRMATION CARRIED OVER to a new command")
    page.wait_for_selector(".explain:not(.explain--wait):not(.explain--live)", timeout=60000)
    settle(page, 1.5)
    expect(page.get_by_role("dialog").count() == 1, "the dialog closed itself when the explanation finished")
    shot(page, "07_second_danger")
    dialog.get_by_role("button", name="Cancel").click()
    settle(page)

    # Admin rights: blocked in the block
    send(page, "sudo pacman -Syu", mode="explain")
    expect("admin rights" in focused_block(page).inner_text(), "sudo command not blocked")
    shot(page, "08_sudo")

    # Off-topic request, then continue anyway
    send(page, "what is the capital of france", mode="ask")
    expect(page.get_by_text("look like a task", exact=False).count() >= 1, "off-topic notice missing")
    shot(page, "09_off_topic")
    page.get_by_role("button", name="continue anyway").click()
    settle(page, 3)
    expect("capital of france" in focused_block(page).inner_text(), "continue anyway did not produce a block")

    # Older blocks focus on click
    older = page.locator("article.block.compact").first
    older.click()
    settle(page, 1.5)
    expect(page.locator("article.block.focused").count() == 1, "clicking an older block did not focus it")

    # Command palette
    page.keyboard.press("Control+k")
    time.sleep(0.6)
    expect(page.locator(".backdrop.open").count() == 1, "ctrl+k did not open the palette")
    page.locator("input.q").fill("history")
    shot(page, "10_palette")
    page.locator("input.q").press("Enter")
    settle(page, 2)
    expect("/history" in page.url, "palette did not navigate to History")

    # History table: click a row to reopen it
    shot(page, "11_history")
    rows = page.locator("tr.row")
    expect(rows.count() >= 5, f"history shows only {rows.count()} rows")
    rows.first.click()
    settle(page, 3)
    expect("/history" not in page.url, "history row did not open the session")
    shot(page, "12_reopened")

    # Folder dialog: go up one level and open it
    before = page.locator(".tbar-title").inner_text()
    page.get_by_role("button", name="cd").click()
    settle(page)
    shot(page, "13_folder_dialog")
    page.get_by_role("dialog").get_by_role("button", name="..").click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Open this folder").click()
    settle(page, 1.5)
    expect(page.locator(".tbar-title").inner_text() != before, "folder did not change")

    # Manual page
    page.get_by_role("link", name="Manual").click()
    settle(page, 1.5)
    expect(page.get_by_text("GHOST(1)").count() >= 1, "manual page missing")
    shot(page, "14_manual")

    # Phone width
    page.set_viewport_size({"width": 400, "height": 1000})
    page.goto(URL)
    page.wait_for_selector("input.in", timeout=120000)
    settle(page, 1.5)
    shot(page, "15_phone")
    browser.close()

print("\nPROBLEMS:\n" + ("\n".join(problems) or "none"))
print("BROWSER ERRORS:\n" + ("\n".join(errors[:15]) or "none"))
sys.exit(1 if problems else 0)
