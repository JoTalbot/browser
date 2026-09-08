#!/usr/bin/env python3
"""Start a GitHub Actions workflow through an already authenticated Octopus browser.

The script attaches to an existing Chrome profile over CDP. It never reads or
copies a Chrome profile directory, cookies, storage state, or passwords.
Because dispatching a workflow is a real external side effect, ``--approved``
is mandatory.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

GITHUB_HOST = "github.com"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class WorkflowInput:
    name: str
    value: str


def _github_only(page: Page) -> None:
    parsed = urlparse(page.url)
    if parsed.hostname != GITHUB_HOST:
        raise RuntimeError(
            f"Ожидался github.com, получен {parsed.hostname or 'unknown'}"
        )


def _set_dispatch_input(page: Page, item: WorkflowInput) -> None:
    candidates = [
        page.locator(f'[name="{item.name}"]'),
        page.get_by_label(item.name, exact=True),
    ]
    for locator in candidates:
        if locator.count() == 0:
            continue
        target = locator.first
        if not target.is_visible():
            continue
        tag = target.evaluate("element => element.tagName.toLowerCase()")
        if tag == "select":
            target.select_option(item.value)
        else:
            target.fill(item.value)
        return
    raise RuntimeError(f"Поле workflow input не найдено: {item.name}")


def _parse_inputs(values: list[str]) -> list[WorkflowInput]:
    result: list[WorkflowInput] = []
    for raw in values:
        name, separator, value = raw.partition("=")
        if not separator or not SAFE_NAME.fullmatch(name):
            raise ValueError(f"Некорректный --input: {raw!r}; ожидается name=value")
        result.append(WorkflowInput(name, value))
    return result


def start_workflow(
    *,
    cdp_url: str,
    repo: str,
    workflow: str,
    branch: str,
    account_email: str,
    github_user: str,
    inputs: list[WorkflowInput],
    approved: bool,
) -> None:
    if not approved:
        raise RuntimeError("Запуск workflow требует --approved")
    if "/" not in repo or any(
        not SAFE_NAME.fullmatch(part) for part in repo.split("/")
    ):
        raise ValueError("repo должен иметь формат owner/name")
    if not SAFE_NAME.fullmatch(workflow):
        raise ValueError("workflow должен быть именем YAML-файла")
    if not branch or any(char in branch for char in "\r\n"):
        raise ValueError("branch некорректен")

    workflow_url = f"https://{GITHUB_HOST}/{repo}/actions/workflows/{workflow}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=10_000)
        if not browser.contexts:
            raise RuntimeError("CDP browser не содержит контекста")
        context = browser.contexts[0]
        page = context.new_page()
        try:
            page.goto(
                f"https://{GITHUB_HOST}/settings/profile",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            _github_only(page)
            body = page.locator("body").inner_text(timeout=10_000)
            if github_user not in body:
                raise RuntimeError(
                    f"В текущей browser-сессии не подтверждён GitHub-пользователь {github_user}"
                )
            print(f"account_check=ok user={github_user} email={account_email}")

            page.goto(workflow_url, wait_until="domcontentloaded", timeout=30_000)
            _github_only(page)
            if repo not in page.url:
                raise RuntimeError("GitHub открыл страницу не того репозитория")

            run_button = page.get_by_role(
                "button", name=re.compile(r"^Run workflow$", re.IGNORECASE)
            ).first
            run_button.wait_for(state="visible", timeout=15_000)
            run_button.click()

            ref = page.locator('[name="ref"]').first
            if ref.count() and ref.is_visible():
                tag = ref.evaluate("element => element.tagName.toLowerCase()")
                if tag == "select":
                    ref.select_option(branch)
                else:
                    ref.fill(branch)

            for item in inputs:
                _set_dispatch_input(page, item)

            dispatch_button = page.get_by_role(
                "button", name=re.compile(r"^Run workflow$", re.IGNORECASE)
            ).last
            dispatch_button.wait_for(state="visible", timeout=10_000)
            dispatch_button.click()

            try:
                page.get_by_text(
                    re.compile(r"successfully requested|workflow run", re.IGNORECASE)
                ).first.wait_for(state="visible", timeout=10_000)
            except PlaywrightTimeoutError:
                # GitHub UI changes its confirmation text; the click itself is
                # the authoritative side effect, while keeping a bounded wait.
                page.wait_for_timeout(1_000)
            print(
                f"workflow_started=true repo={repo} workflow={workflow} branch={branch}"
            )
        finally:
            page.close()
            # Do not close the user-owned Chrome context; sync_playwright()
            # only disconnects from CDP when the block exits.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cdp-url",
        default=os.getenv("OCTOPUS_BROWSER_SECONDARY_CDP_URL", "http://127.0.0.1:9224"),
    )
    parser.add_argument("--repo", default="JoTalbot/octopus")
    parser.add_argument(
        "--workflow", required=True, help="YAML filename in .github/workflows/"
    )
    parser.add_argument("--branch", default="main")
    parser.add_argument("--account-email", default="jo.talbot@gmail.com")
    parser.add_argument("--github-user", default="JoTalbot")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="workflow_dispatch input; may be repeated",
    )
    parser.add_argument(
        "--approved",
        action="store_true",
        help="explicitly approve the workflow dispatch side effect",
    )
    args = parser.parse_args()

    try:
        start_workflow(
            cdp_url=args.cdp_url,
            repo=args.repo,
            workflow=args.workflow,
            branch=args.branch,
            account_email=args.account_email,
            github_user=args.github_user,
            inputs=_parse_inputs(args.input),
            approved=args.approved,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(
            f"workflow_started=false error={type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
