"""Browser transport policy and session failure semantics without live websites."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-browser')
from aries.workspace import browser
from aries.news.fetch import FetchResult, FetchRefused


async def test_egress_and_redirect_rules():
    row = {'requests': 0, 'bytes': 0, 'blocked': 0, 'network': asyncio.Semaphore(1)}
    route = SimpleNamespace(abort=AsyncMock(), fulfill=AsyncMock())
    with patch.object(browser, 'fetch', AsyncMock()) as fetch:
        await browser._route(route, SimpleNamespace(method='POST', url='https://www.python.org'), row)
        check('non-GET requests never reach network transport', not fetch.called and route.abort.called)
    result = FetchResult('https://www.python.org/about/', 200, b'<p>About Python</p>', 'text/html')
    with patch.object(browser, 'fetch', AsyncMock(return_value=result)):
        await browser._route(route, SimpleNamespace(method='GET', url='https://www.python.org/about'), row)
    check('redirect changes browser origin instead of disguising destination', route.fulfill.call_args.kwargs['status'] == 302 and route.fulfill.call_args.kwargs['headers']['location'] == result.url)
    with patch.object(browser, 'fetch', AsyncMock(side_effect=FetchRefused('private address'))):
        await browser._route(route, SimpleNamespace(method='GET', url='http://127.0.0.1'), row)
    check('refused fetches are aborted in the browser', row['blocked'] == 2)
    row['requests'] = 100
    with patch.object(browser, 'fetch', AsyncMock()) as fetch:
        await browser._route(route, SimpleNamespace(method='GET', url='https://www.python.org'), row)
        check('session request budget is enforced before fetching', not fetch.called)


def test_expired_session_is_not_replayed():
    try:
        browser.session('missing')
    except ValueError as exc:
        check('closed sessions require a new navigation', 'closed or expired' in str(exc))
    else:
        check('closed sessions require a new navigation', False)


async def test_main_navigation_normalizes_prefetched_redirect_destination():
    response=FetchResult('https://www.python.org',200,b'<html>Python</html>','text/html')
    page=SimpleNamespace(goto=AsyncMock(return_value=SimpleNamespace(ok=True)), locator=lambda _:SimpleNamespace(wait_for=AsyncMock()))
    row={'page':page,'requests':0,'bytes':0,'blocked':0,'network':asyncio.Semaphore(1)}
    route=SimpleNamespace(abort=AsyncMock(),fulfill=AsyncMock())
    with patch.object(browser,'fetch',AsyncMock(return_value=response)) as fetch:
        await browser.navigate(row,'http://www.python.org')
        await browser._route(route,SimpleNamespace(method='GET',url='https://www.python.org/'),row)
    check('main document redirects resolve before navigation',page.goto.call_args.args[0]=='https://www.python.org')
    check('normalized document is fulfilled without a browser redirect loop',route.fulfill.call_args.kwargs['status']==200 and fetch.call_count==1)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
