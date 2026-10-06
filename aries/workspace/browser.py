"""Dedicated, bounded public-web sessions. No borrowed profile or credentials.

All HTTP resources use the existing pinned-DNS transport. Direct Chromium egress
is disabled by a dead proxy; routed GETs are fulfilled by ARIES. WebSockets,
service workers, uploads, downloads and non-GET requests are unavailable here.
"""
import asyncio
import os
import time
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urldefrag

from aries.news.fetch import fetch

_driver = None
_browser = None
_sessions = {}
_start_lock = asyncio.Lock()
MAX_SESSIONS = 6


async def start():
    global _driver, _browser
    async with _start_lock:
        if _browser and _browser.is_connected():
            return _browser
        from playwright.async_api import async_playwright
        if _driver:
            await _driver.stop()
        _driver = await async_playwright().start()
        try:
            _browser = await _driver.chromium.launch(
                headless=False, chromium_sandbox=False,
                executable_path=str(Path(__file__).resolve().parents[2] / "scripts/aries-browser"),
                env={**os.environ, "ARIES_CHROMIUM_BIN": _driver.chromium.executable_path},
                proxy={"server": "http://127.0.0.1:9", "bypass": "<-loopback>"},
                args=["--disable-background-networking", "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
        except BaseException:
            await _driver.stop()
            _driver = None
            raise
        return _browser


def session(session_id):
    row = _sessions.get(session_id)
    if not row or row["page"].is_closed():
        raise ValueError("This browser session is closed or expired; open the website again")
    row["used"] = time.monotonic()
    return row


async def _route(route, request, row):
    if request.method != "GET" or urlsplit(request.url).scheme not in {"https", "http"}:
        row["blocked"] += 1
        await route.abort()
        return
    row["requests"] += 1
    if row["requests"] > 100 or row["bytes"] > 20_000_000:
        row["blocked"] += 1
        await route.abort()
        return
    try:
        result = row.get('documents', {}).pop(request.url, None)
        if result is None:
            gate = row.get('media_network', row['network']) if getattr(request,'resource_type','') in {'image','font','media'} else row['network']
            async with gate:
                result = await asyncio.wait_for(fetch(request.url, max_bytes=2_000_000, timeout=12, accept="*/*"), 15)
        if result.truncated:
            raise ValueError("Resource exceeded its limit")
        row["bytes"] += len(result.body)
        # The browser must see the final URL, not render a redirected document
        # under its old origin. Every subsequent route is validated again.
        if result.url != request.url:
            await route.fulfill(status=302, headers={"location": result.url})
        else:
            await route.fulfill(status=result.status, body=result.body,
                                content_type=result.content_type or "application/octet-stream")
    except Exception:
        row["blocked"] += 1
        await route.abort()


async def navigate(row, url):
    # Playwright does not re-route every redirect request. Resolve a main
    # document through the pinned transport first, then navigate its final URL.
    result = await fetch(url, max_bytes=2_000_000, timeout=20, accept='text/html,application/xhtml+xml')
    if not result.ok or result.truncated:
        raise ValueError('The destination did not return a complete successful document')
    if result.content_type not in {'text/html','application/xhtml+xml','text/plain'}:
        raise ValueError('Open this document format in its application')
    final = result.url
    key = urldefrag(final)[0]
    if not urlsplit(key).path:
        key += '/'
    row.setdefault('documents', {})[key] = replace(result, url=key)
    response = await row['page'].goto(final, wait_until='commit', timeout=30000)
    if not response or not response.ok:
        raise ValueError('The browser did not load the resolved destination')
    # Parser-blocking head scripts can exhaust more than one bounded resource
    # fetch before the body is attached. Keep a bounded document allowance
    # inside the bridge's 100-second request deadline.
    await row['page'].locator('body').wait_for(state='attached', timeout=45000)


async def open_page(url, owner=""):
    from aries.workspace.service import safe_link
    if not safe_link(url):
        raise ValueError("A public HTTP or HTTPS URL is required")
    browser = await start()
    async with _start_lock:
        # Never silently close a live session when the limit is reached.
        for key, row in list(_sessions.items()):
            if row["page"].is_closed():
                await row["context"].close()
                _sessions.pop(key, None)
        if len(_sessions) >= MAX_SESSIONS:
            raise ValueError("Six browser sessions are open; close a session before opening another")
        context = await browser.new_context(accept_downloads=False, service_workers="block", viewport={"width": 1200, "height": 800})
        page = await context.new_page()
        row = {"context": context, "page": page, "owner": owner, "used": time.monotonic(), "blocked": 0,
               "requests": 0, "bytes": 0, "network": asyncio.Semaphore(6), "media_network": asyncio.Semaphore(2), "lock": asyncio.Lock()}
        key = uuid.uuid4().hex[:12]
        _sessions[key] = row
    try:
        await context.route("**/*", lambda route, request: _route(route, request, row))
        await context.route_web_socket("**/*", lambda ws: ws.close())
        page.on("dialog", lambda dialog: dialog.dismiss())
        context.on("page", lambda popup: popup.close() if popup != page else None)
        page.set_default_timeout(8000)
        await navigate(row, url)
        return await observe(key)
    except BaseException:
        await context.close()
        _sessions.pop(key, None)
        raise


async def observe(key):
    row = session(key)
    page = row["page"]
    # Only fixed inspection code runs here, never source/model-provided JS.
    state = await page.evaluate("""() => ({title: document.title, url: location.href,
      text: (document.body?.innerText || '').slice(0, 10000),
      links: Array.from(document.querySelectorAll('a[href]')).filter(a => a.innerText.trim())
        .slice(0, 40).map(a => ({name:a.innerText.trim().slice(0,160),url:a.href})),
      fields: Array.from(document.querySelectorAll('input:not([type=password]),textarea'))
        .filter(e => e.type !== 'hidden').slice(0,20)
        .map(e => ({label: e.labels?.[0]?.innerText || e.getAttribute('aria-label') || e.placeholder || '', type:e.type}))})""")
    state['scroll'] = await page.evaluate('() => ({x:window.scrollX,y:window.scrollY})')
    state.update(session=key, blocked_resources=row["blocked"], requests=row["requests"],
                 evidence="Actual URL and rendered DOM from the dedicated public browser; body preview capped at 10,000 characters")
    return state


async def elements(key):
    """Server-owned element handles; IDs cannot become arbitrary selectors or JS."""
    row = session(key)
    # A fresh observation deliberately expires old IDs, avoiding silent retargets.
    previous = row.pop('elements', {})
    for item in previous.values():
        await item['handle'].dispose()
    handles = await row['page'].query_selector_all('a[href],button,input:not([type=password]):not([type=hidden]),textarea,select,[role=button]')
    rows, mapping = [], {}
    for handle in handles[:200]:
        if not await handle.is_visible():
            await handle.dispose()
            continue
        item = await handle.evaluate("""e => ({role:e.getAttribute('role') || ({A:'link',BUTTON:'button',INPUT:'textbox',TEXTAREA:'textbox',SELECT:'combobox'}[e.tagName] || 'control'),
          name:(e.getAttribute('aria-label') || e.labels?.[0]?.innerText || e.innerText || e.getAttribute('placeholder') || '').slice(0,160),
          tag:e.tagName, type:e.type || '', href:e.tagName==='A' ? e.href : null})""")
        key_id = 'element_' + uuid.uuid4().hex[:16]
        mapping[key_id] = {'handle':handle,'url':row['page'].url, 'identity':item}
        rows.append({**item,'id':key_id,'visible':True,'enabled':await handle.is_enabled()})
    for handle in handles[200:]:
        await handle.dispose()
    row['elements'] = mapping
    return {'session':key,'url':row['page'].url,'elements':rows,'truncated':len(handles)>200}


async def element_target(row, element_id):
    item = row.get('elements',{}).get(element_id)
    if not item or row['page'].url != item['url']:
        raise ValueError('TARGET_NOT_FOUND: element observation expired; observe again')
    handle = item['handle']
    if not await handle.evaluate('e => e.isConnected') or not await handle.is_visible() or not await handle.is_enabled():
        raise ValueError('TARGET_NOT_FOUND: observed element is detached, hidden or disabled')
    return handle, item['identity']


async def click_element(key, element_id):
    row = session(key)
    async with row['lock']:
        handle, identity = await element_target(row,element_id)
        if identity['tag']=='A':
            destination = await handle.evaluate('e => e.href')
            if destination != identity['href']:
                raise ValueError('TARGET_NOT_FOUND: observed link destination changed')
            await navigate(row,destination)
        else:
            # Public contexts still block POST, credentials, popups and downloads.
            await handle.click(timeout=8000)
        return await observe(key)


async def type_element(key, element_id, value):
    row = session(key)
    async with row['lock']:
        handle, identity = await element_target(row,element_id)
        actual_type = await handle.get_attribute('type')
        if identity['tag'] not in {'INPUT','TEXTAREA'} or actual_type in {'password','file','hidden'}:
            raise ValueError('PERMISSION_REQUIRED: protected or unsupported input')
        await handle.fill(value)
        return {**await observe(key),'element_id':element_id,'observed_value':await handle.input_value()}


async def element_value(key, element_id):
    row = session(key)
    handle, _ = await element_target(row,element_id)
    return {'session':key,'element_id':element_id,'observed_value':await handle.input_value()}


async def navigate_page(key, url):
    row = session(key)
    async with row['lock']:
        await navigate(row,url)
        return await observe(key)


async def history_page(key, direction):
    row = session(key)
    async with row['lock']:
        if direction not in {'back','forward'}:
            raise ValueError('Unknown history operation')
        response = await (row['page'].go_back() if direction=='back' else row['page'].go_forward())
        if response is None:
            raise ValueError('TARGET_NOT_FOUND: no observable history navigation')
        return await observe(key)


async def scroll_page(key, pixels):
    row = session(key)
    delta = int(pixels)
    if abs(delta)>4000: raise ValueError('Scroll is bounded to 4000 pixels')
    async with row['lock']:
        await row['page'].evaluate('(dy) => window.scrollBy(0,dy)',delta)
        return await observe(key)


async def wait_page(key, milliseconds):
    delay = int(milliseconds)
    if not 0<=delay<=10000: raise ValueError('Wait is bounded to 10 seconds')
    await asyncio.sleep(delay/1000)
    return await observe(key)


async def follow(key, label):
    row = session(key)
    async with row["lock"]:
        page = row["page"]
        from urllib.parse import urljoin
        from aries.workspace.service import safe_link
        # Use the same atomic DOM name calculation as observation. Lazy role
        # locators can change membership while a site's menu CSS/JS loads.
        hrefs = []
        for _ in range(8):
            hrefs = await page.locator('a[href]').evaluate_all(
                '(anchors, label) => anchors.filter(a => a.innerText.trim().slice(0,160) === label).map(a => a.href)', label)
            if hrefs:
                break
            await asyncio.sleep(.25)
        if not 1 <= len(hrefs) <= 20:
            raise ValueError("No bounded set of links matches that accessible name")
        destinations = {urljoin(page.url, href) for href in hrefs if href}
        if len(destinations) != 1:
            raise ValueError("This link name has different destinations; choose a more specific link")
        destination = destinations.pop()
        if not safe_link(destination):
            raise ValueError("This is not an HTTP navigation link")
        # Navigate the independently resolved href. Do not execute arbitrary
        # onclick handlers when the user requested following a public link.
        await navigate(row, destination)
        return await observe(key)


async def fill(key, label, value):
    row = session(key)
    async with row["lock"]:
        page = row["page"]
        field = page.get_by_label(label, exact=True)
        if await field.count() != 1:
            raise ValueError("The field label must match exactly one control")
        if await field.get_attribute("type") in {"password", "file", "hidden"}:
            raise ValueError("Passwords and file uploads are not supported by this public session")
        await field.fill(value)
        if await field.input_value() != value:
            raise ValueError("Read-back did not match the requested field value")
        state = await observe(key)
        state["field_verified"] = label
        return state


async def inventory():
    """Current owned windows, including manual close state, without opening a browser."""
    return [{"session": key, "owner": row.get("owner", ""), "open": not row["page"].is_closed(),
             "url": row["page"].url if not row["page"].is_closed() else None}
            for key, row in list(_sessions.items())]


async def close(key):
    row = session(key)
    async with row["lock"]:
        await row["context"].close()
        _sessions.pop(key, None)
    return {"session": key, "closed": True}


async def close_all():
    global _browser, _driver
    if _browser:
        await _browser.close()
    if _driver:
        await _driver.stop()
    _browser = _driver = None
    _sessions.clear()


def cards(state):
    if state.get("closed"):
        return [{"title": "Browser session closed", "text": state["session"], "evidence": "Owned browser context closed"}]
    result = [{"title": state["title"], "text": state["text"][:2500], "url": state["url"],
               "browser_session": state["session"], "evidence": state["evidence"]}]
    result.extend({"title": link["name"], "text": link["url"], "browser_session": state["session"],
                   "browser_link": link["name"], "evidence": "Link observed in the rendered document"}
                  for link in state["links"][:20] if urlsplit(link["url"]).scheme in {"http", "https"})
    result.extend({"title": "Field: " + field["label"], "text": field["type"],
                   "browser_session": state['session'], "browser_field": field['label'],
                   "evidence": "Input label observed in the current DOM"} for field in state["fields"] if field['label'])
    return result


if os.environ.get('INVOCATION_ID') and os.environ.get('APP_ENV') != 'test' and not os.environ.get('ARIES_BROWSER_WORKER'):
    from aries.workspace.browser_bridge import request as _request
    def _remote(name):
        async def call(*args):
            return await _request(name, *args)
        return call
    for _name in ('open_page','observe','follow','fill','close','close_all','inventory','elements','click_element','type_element','element_value','navigate_page','history_page','scroll_page','wait_page'):
        globals()[_name] = _remote(_name)
