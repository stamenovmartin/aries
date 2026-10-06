"""Real Chromium DOM controls in an isolated fixture; not live acceptance."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,run_module
bootstrap('aries-m15-browser')
from aries.workspace import browser
from playwright.async_api import async_playwright

async def test_real_dom_ids_and_values():
    async with async_playwright() as pw:
        chromium=await pw.chromium.launch(headless=True)
        context=await chromium.new_context()
        page=await context.new_page()
        await page.set_content('<title>Fixture</title><label for="q">Search</label><input id="q"><input type="password"><button>Continue</button><div style="height:4000px">Content</div>')
        browser._sessions['fixture']={'page':page,'context':context,'lock':asyncio.Lock(),'owner':'fixture','blocked':0,'requests':0}
        try:
            result=await browser.elements('fixture')
            check('real DOM exposes input and button',len(result['elements'])==2)
            check('password omitted',not any(r['type']=='password' for r in result['elements']))
            target=next(e['id'] for e in result['elements'] if e['name']=='Search')
            typed=await browser.type_element('fixture',target,'Theory of Mind')
            check('type readback from real DOM',typed['observed_value']=='Theory of Mind')
            check('independent field reread',(await browser.element_value('fixture',target))['observed_value']=='Theory of Mind')
            await browser.elements('fixture')
            try:await browser.type_element('fixture',target,'wrong')
            except ValueError as exc:check('expired ID rejected','TARGET_NOT_FOUND' in str(exc))
            else:check('expired ID rejected',False)
            result=await browser.elements('fixture');target=next(e['id'] for e in result['elements'] if e['name']=='Search')
            await page.locator('#q').evaluate("e=>e.remove()")
            try:await browser.type_element('fixture',target,'wrong')
            except ValueError as exc:check('detached control rejected','TARGET_NOT_FOUND' in str(exc))
            else:check('detached control rejected',False)
            observed=await browser.scroll_page('fixture','500')
            check('scroll observed from viewport',observed['scroll']['y']==500)
        finally:
            browser._sessions.pop('fixture',None)
            await context.close();await chromium.close()

if __name__=='__main__':raise SystemExit(run_module(sys.modules[__name__]))
