#!/usr/bin/env python3
"""Build offline HTML from publication Markdown and rendered Mermaid SVGs.
Use repository .venv Python. SVG rendering requires --mermaid-js PATH, once;
HTML rebuild thereafter uses stored SVGs and no network.
"""
from pathlib import Path
import argparse, asyncio, hashlib, html, json, re
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
SLIDES=[
('ARIES','Evidence-Verified Agentic Execution in a Local Linux Environment','Martin Stamenov\nЛокален Linux agent · истражувачки прототип\n17 септември 2026'),
('Проблемот','Exit code 0 ≠ постигната цел','Launcher може да успее без видлив прозорец.\nBrowser request може да заврши на друга страница.\nModel-generated success не е доказ.'),
('Главен принцип','Model output is not evidence','Planner предлага. Executor дејствува.\nVerifier ја набљудува состојбата.\nTask done бара проверен goal condition.'),
('Research questions','Четири прашања','RQ1 · Дали verification открива false-success claims?\nRQ2 · Може ли planning да остане capability-constrained?\nRQ3 · Дали evidence преживува failures и restarts?\nRQ4 · Како reproducibly се споредува retrieval?'),
('Architecture','Од цел до доказ','@diagram:1'),
('Execution','Проверка на реалната датотека','@diagram:2'),
('Step lifecycle','Секој исход останува видлив','@diagram:3'),
('Policy boundaries','Capability name + validated arguments','Registry → schema → policy → executor.\nНема model-generated shell execution.\nНема автоматско deletion, killing или installation.\nValid JSON не значи semantic correctness.'),
('Honesty gap','Две мерки, различни прашања','H_raw = reported rate − verified rate\nFalse claims = reported success AND unmet\nRaw claims и финалните user-visible пораки се различни.\nVerified impossible task може да значи правилно одбивање.'),
('Operator experiment','372 trials · историски run','31 tasks × 4 variants × 3 repeats\nB0 launcher · B1 keywords · B2 model · A ARIES\n60 control trials → 8 contaminated excluded\n52/52 eligible controls correctly UNMET'),
('Measured results','Verification ≠ подобар planner','@table'),
('Interpretation','Null result останува null result','A − B2 = 0.0 pp verified rate.\nДвете варијанти произведуваат 4 raw false claims.\nVerifier ги идентификува несовпаѓањата.\nНема независна user study за финалното reporting.'),
('Threats to validity','Што не смееме да заклучиме','Fixed variant order; cold-browser bias за B0.\nСамо 3–4 clean app trials по варијанта.\nЕдна машина, една session, qwen2.5:7b.\n3 од 4 model false claims: ист weather task.'),
('Product evidence','11/11 full · 7/7 core','Историски passing demo artifacts од 17 септември.\nПретходни full attempts: 1/11, 9/11, 10/11.\nMissing-file task мора да fail-не за test да помине.\nEngineering acceptance ≠ scientific superiority.'),
('Retrieval comparison','15/20 → 19/20','4 подобрувања · 0 регресии\nExact paired test: p = 0.125\n20 developer-labelled cases; нема held-out validation.\nDevelopment evidence, не statistical superiority.'),
('M14 milestone','Bounded multi-step execution','@diagram:4'),
('M14 live acceptance','4/4 сценарија · реален local model','File done · 2 steps · 10.734 s\nSystem done · 1 step · 4.166 s\nBrowser done · 2 steps · 10.853 s\nMissing-file failed, test PASS · 1 step · 4.154 s\n10 planner calls · 36,039 native tokens\nПосле 0/4, 0/4, 2/4, 3/4, 3/4: development evidence'),
('M15 / conclusion','Што навистина се случи?','Freeze code и independently labelled benchmark.\nRandomized order; dedicated desktop session.\nCold vs Learned: success, tokens, steps, latency.\nСекое success тврдење мора да има проверлив доказ.')]
CSS='''*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e9eef6;font-family:Arial,"DejaVu Sans",sans-serif}section{display:none;min-height:100vh;padding:6vh 7vw 7vh}section.active{display:flex;flex-direction:column}header{font-size:17px;text-transform:uppercase;letter-spacing:.16em;color:#73d8c3}h1{font-size:clamp(30px,4.8vw,68px);line-height:1.12;font-weight:650;max-width:1100px;margin:.7em 0}p,li{font-size:clamp(18px,2.15vw,31px);line-height:1.6}p{margin:.3em 0}footer{margin-top:auto;padding-top:2em;color:#a6b8cc;font-size:14px}figure{margin:0;flex:1;display:flex;align-items:center;justify-content:center;background:white;border-radius:12px;padding:20px;max-height:58vh}figure svg{max-width:100%;max-height:52vh;height:auto}table{border-collapse:collapse;width:100%;font-size:clamp(17px,2vw,28px)}td,th{padding:15px 12px;border-bottom:1px solid #39465a;text-align:left}th{color:#73d8c3}button{background:#203246;color:#fff;border:1px solid #61758e;padding:8px 16px;border-radius:5px;cursor:pointer}nav{position:fixed;bottom:15px;right:25px;display:flex;gap:8px;align-items:center}a{color:#73d8c3}.hint{font-size:12px;color:#b7c7d7}@media print{@page{size:landscape;margin:0}body{background:white;color:#152235}section,section.active{display:flex;height:100vh;min-height:0;page-break-after:always;break-after:page;padding:35px 55px}h1{font-size:38px}p,li{font-size:22px}header{color:#17665e}footer{color:#445}figure{max-height:60vh}nav{display:none}table{font-size:20px}a{color:#17665e}}'''
async def render(js):
 from playwright.async_api import async_playwright
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
  page=await browser.new_page()
  await page.set_content('<html><body></body></html>')
  await page.add_script_tag(path=str(js))
  await page.evaluate("mermaid.initialize({startOnLoad:false,theme:'neutral',securityLevel:'strict',fontFamily:'Arial',flowchart:{htmlLabels:false},sequence:{useMaxWidth:true}})")
  for f in sorted((ROOT/'diagrams').glob('*.mmd')):
   svg=await page.evaluate("async ({text,id}) => (await mermaid.render(id,text)).svg",{'text':f.read_text(),'id':f.stem.replace('-','')})
   f.with_suffix('.svg').write_text(svg)
  await browser.close()
def build():
 sections=[];md=['# ARIES: Evidence-Verified Agentic Execution in a Local Linux Environment\n\n**Martin Stamenov**\n\nHistorical results and M14 are separate. See [paper](paper.md) and [M14 addendum](m14-results.md).\n']
 for i,(kicker,title,body) in enumerate(SLIDES,1):
  markdown=body
  if body.startswith('@diagram:'):
   n=body.split(':')[1];f=ROOT/'diagrams'/f'figure-{n}.svg'
   content='<figure>'+f.read_text()+'</figure>'
   markdown='```mermaid\n'+f.with_suffix('.mmd').read_text()+'```'
  elif body=='@table':
   rows=[['Variant','Verified / n','H_raw','False claims'],['B0','57 / 68','+11.8 pp','8'],['B1','45 / 67','0.0 pp','0'],['B2','60 / 67','+6.0 pp','4'],['A','60 / 67','+6.0 pp','4']]
   content='<table>'+''.join('<tr>'+''.join(f'<{"th" if j==0 else "td"}>{x}</{"th" if j==0 else "td"}>' for x in row)+'</tr>' for j,row in enumerate(rows))+'</table>'
   markdown='\n'.join('| '+' | '.join(row)+' |' for row in [rows[0],['---']*4,*rows[1:]])
  else:content=''.join('<p>'+html.escape(line)+'</p>' for line in body.splitlines())
  sections.append(f'<section id="slide-{i}" aria-label="Slide {i}" class="{"active" if i==1 else ""}"><header>{html.escape(kicker)}</header><h1>{html.escape(title)}</h1>{content}<footer>ARIES · Martin Stamenov &nbsp; | &nbsp; {i:02d} / {len(SLIDES)} &nbsp; | &nbsp; Sources and caveats: paper.md · m14-results.md</footer></section>')
  md.append(f'\n---\n\n## {i}. {title}\n\n{markdown}\n')
 script='''let current=0;const slides=[...document.querySelectorAll('section')];function show(n){current=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,i)=>{s.classList.toggle('active',i===current);s.setAttribute('aria-hidden',i!==current)});document.getElementById('count').textContent=(current+1)+' / '+slides.length;history.replaceState(null,'','#'+(current+1))}document.getElementById('prev').onclick=()=>show(current-1);document.getElementById('next').onclick=()=>show(current+1);document.addEventListener('keydown',e=>{if(['ArrowRight','PageDown',' '].includes(e.key)){e.preventDefault();show(current+1)}if(['ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();show(current-1)}if(e.key==='Home')show(0);if(e.key==='End')show(slides.length-1)});show((parseInt(location.hash.slice(1))||1)-1);'''
 (ROOT/'presentation.html').write_text('<!doctype html><html lang="mk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ARIES — Martin Stamenov</title><style>'+CSS+'</style><body>'+''.join(sections)+'<nav aria-label="Slide navigation"><span class="hint">← → · Home / End · Ctrl+P</span><button id="prev" aria-label="Previous slide">←</button><span id="count" aria-live="polite"></span><button id="next" aria-label="Next slide">→</button></nav><script>'+script+'</script></body></html>')
 (ROOT/'slides.md').write_text('\n'.join(md))
 sources=['experiments/operator/results.jsonl','experiments/operator/summary.json','experiments/operator/config.yaml','experiments/operator/tasks.jsonl','experiments/demo/20260917T185011Z-72477e/results.json','experiments/demo/20260917T185338Z-04f0a5/results.json','experiments/learning/comparison-20260917T184530443474Z.json']
 sources += [str(p.relative_to(REPO)) for p in sorted((REPO/'experiments/agent/20260917T204354Z-fb8722').rglob('*.json'))]
 sources += [str(p.relative_to(REPO)) for p in sorted((REPO/'experiments/agent/20260917T204843Z-1ae7a7').rglob('*.json'))]
 sources += ['experiments/agent/'+run+'/result.json' for run in ['20260917T203400Z-51901a','20260917T203531Z-505cc8','20260917T203544Z-497bea','20260917T203732Z-b2ba9e','20260917T204217Z-2a255c']]
 manifest={'publication_date':'2026-09-17','scope':'historical Operator + product + retrieval; M14 live acceptance 20260917T204354Z-fb8722 and prior attempts separately documented','artifacts':[{'path':s,'sha256':hashlib.sha256((REPO/s).read_bytes()).hexdigest()} for s in sources]}
 (ROOT/'evidence-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
def build_paper():
 import markdown
 source=(ROOT/'paper.md').read_text()
 index=iter(range(1,5))
 source=re.sub(r'```mermaid\n.*?```',lambda m:'<figure>'+ (ROOT/'diagrams'/f'figure-{next(index)}.svg').read_text()+'</figure>',source,flags=re.S)
 content=markdown.markdown(source,extensions=['tables','fenced_code'])
 css='body{max-width:880px;margin:55px auto;padding:0 30px;color:#172335;font:17px/1.7 Georgia,serif}h1{font:700 32px/1.3 Arial,sans-serif}h2{font:600 24px Arial,sans-serif;margin-top:1.7em}table{border-collapse:collapse;width:100%;font:14px/1.4 Arial,sans-serif}td,th{border-bottom:1px solid #ccd5df;padding:9px;text-align:left}a{color:#096c70}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f8;padding:15px;font-size:12px}figure{margin:25px 0;break-inside:avoid}svg{width:100%;max-height:500px}p,li{orphans:3;widows:3}@media print{@page{size:A4;margin:20mm}body{margin:0;padding:0;font-size:10.5pt;line-height:1.5}h1{font-size:22pt}h2{font-size:15pt;break-after:avoid}h3{break-after:avoid}table{font-size:8.5pt}a{color:inherit;text-decoration:none}}'
 (ROOT/'paper.html').write_text('<!doctype html><html lang="mk"><meta charset="utf-8"><title>ARIES — Martin Stamenov</title><style>'+css+'</style><body>'+content+'</body></html>')

async def pdf_and_check():
 from playwright.async_api import async_playwright
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
  page=await browser.new_page(viewport={'width':1440,'height':900})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto((ROOT/'presentation.html').as_uri())
  assert await page.locator('section.active').count()==1
  await page.keyboard.press('ArrowRight');assert await page.locator('#slide-2').get_attribute('class')=='active'
  await page.keyboard.press('End');assert await page.locator('#slide-18').get_attribute('class')=='active'
  await page.keyboard.press('Home')
  await page.screenshot(path=str(ROOT/'presentation-preview.png'))
  await page.pdf(path=str(ROOT/'presentation.pdf'),print_background=True,prefer_css_page_size=True)
  if (ROOT/'paper.html').exists():
   await page.goto((ROOT/'paper.html').as_uri())
   await page.pdf(path=str(ROOT/'paper.pdf'),print_background=True,prefer_css_page_size=True)
  assert not errors,errors
  print('18 slides built; Mermaid SVGs present; keyboard controls passed; PDF exported; no page errors')
  await browser.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--mermaid-js',type=Path);parser.add_argument('--pdf',action='store_true');parser.add_argument('--paper',action='store_true');args=parser.parse_args()
 if args.mermaid_js:asyncio.run(render(args.mermaid_js))
 build()
 if args.paper:build_paper()
 if args.pdf:asyncio.run(pdf_and_check())
