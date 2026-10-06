"""Real local files, changed-state controls, bounded context eligibility."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-m15-files')
from agentic_core.database.base import async_session
from aries.workspace.registry import registry
from aries.workspace import file_capabilities as files, working_context
from aries.workspace.models import WorkspaceGoal

async def test_real_files():
    await reset_db()
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        root=Path(directory);src=root/'notes.txt';src.write_text('Theory of Mind methodology: controlled experiments')
        async with async_session() as db:
            ctx={'db':db,'task_id':'test','goal':'copy file'}
            meta=await files.metadata({'path':str(src)},ctx)
            args={'path':str(src),'destination':str(root/'copy.txt'),'expected_sha256':meta['sha256']}
            result=await files.copy_file(args,ctx)
            check('copy independently verified',(await files.verify_copy(args,result,ctx))['met'])
            try:await files.copy_file(args,ctx)
            except FileExistsError:check('copy never overwrites',True)
            else:check('copy overwrite rejected',False)
            edit={'path':str(src),'expected_sha256':meta['sha256'],'old_text':'controlled','new_text':'paired'}
            result=await files.edit_file(edit,ctx)
            check('edit independently verified',(await files.verify_edit(edit,result,ctx))['met'])
            try:await files.edit_file(edit,ctx)
            except ValueError:check('stale approved hash rejected',True)
            else:check('stale edit rejected',False)
            args['path']=args['destination'];args['destination']=str(root/'renamed.txt')
            result=await files.move_file(args,ctx)
            check('rename observes destination and absent source',(await files.verify_move(args,result,ctx))['met'])
            search={'path':directory,'query':'Theory of Mind','extension':'.txt'}
            result=await files.semantic_search(search,ctx)
            check('description finds content beyond filename',len(result['matches'])==2 and all(r['text_matches'] for r in result['matches']))
            check('search candidate hashes independently checked',(await files.verify_search(search,result,ctx))['met'])
            src.write_text('changed')
            check('changed candidate fails verification',not (await files.verify_search(search,result,ctx))['met'])
    check('file mutation approval boundary',all(registry.get('file.'+n).requires_approval for n in ('edit','copy','move','rename')))

async def test_working_context():
    await reset_db()
    async with async_session() as db:
        def row(id,path,age=0):
            return WorkspaceGoal(id=id,request='read',state='done',updated_at=datetime.utcnow()-timedelta(minutes=age),result_json=json.dumps({'evidence':[{'evidence_id':id,'verified':True,'data':{'path':path}}]}))
        db.add(row('old','/expired.txt',40));db.add(row('new','/recent.txt'));await db.commit()
        text,ref=await working_context.resolve(db,'Read it')
        check('recent unique reference resolved',text=='Read /recent.txt' and ref['resolved']['task_id']=='new')
        check('expired reference excluded',len((await working_context.current(db))['entities'])==1)
        db.add(row('second','/other.txt'));await db.commit()
        try:await working_context.resolve(db,'Open it')
        except ValueError as exc:check('ambiguous references ask rather than guess','AMBIGUOUS' in str(exc))
        else:check('ambiguity rejected',False)

if __name__=='__main__':run_module(sys.modules[__name__])
