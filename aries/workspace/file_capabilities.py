"""Bounded file extensions. Mutations require reviewed paths and content hashes."""
import asyncio
import hashlib
import os
import re
import stat
from pathlib import Path
from datetime import datetime, timezone
from pydantic import Field
from aries.workspace.capability_types import Input, Capability
from aries.workspace.filesystem import open_nofollow

class PathInput(Input):
    path: str = Field(min_length=1,max_length=2048)
class CopyInput(PathInput):
    destination: str = Field(min_length=1,max_length=2048)
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
class SemanticInput(PathInput):
    query: str = Field(min_length=1,max_length=300)
    extension: str = Field(default='',max_length=16)
    modified_after: str | None = Field(default=None,max_length=40)
    modified_before: str | None = Field(default=None,max_length=40)

async def path_for(ctx,raw,write=False):
    from aries.workspace.capabilities import checked_path
    return await checked_path(ctx['db'],raw,write=write)

def snapshot(path):
    fd=open_nofollow(path,os.O_RDONLY|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>20_000_000:
            raise ValueError('Only regular files up to 20 MB are supported')
        digest=hashlib.sha256(); size=0
        while chunk:=f.read(65536):
            size+=len(chunk)
            if size>20_000_000:raise ValueError('File grew beyond limit')
            digest.update(chunk)
    return {'path':str(path),'size':size,'sha256':digest.hexdigest(),'modified_at':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'inode':st.st_ino,'observed_at':datetime.now(timezone.utc).isoformat()}

async def metadata(args,ctx):
    return await asyncio.to_thread(snapshot,await path_for(ctx,args['path']))
async def verify_metadata(args,result,ctx):
    fresh=await metadata(args,ctx)
    return {'met':fresh['sha256']==result['sha256'],'type':'file_state','data':fresh}

def copy_bytes(source,destination,expected):
    # Hold the source descriptor through hashing/copy; never follow symlinks.
    with os.fdopen(open_nofollow(source,os.O_RDONLY|os.O_NONBLOCK),'rb') as src:
        st=os.fstat(src.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>20_000_000:raise ValueError('Unsupported source')
        content=src.read(20_000_001)
        if len(content)>20_000_000 or hashlib.sha256(content).hexdigest()!=expected:raise ValueError('Source hash differs from approved content')
    with os.fdopen(open_nofollow(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL),'wb') as dst:
        dst.write(content);dst.flush();os.fsync(dst.fileno())
    return {'path':str(source),'destination':str(destination),'expected_sha256':expected,'copy_requested':True}

async def copy_file(args,ctx):
    source=await path_for(ctx,args['path'])
    destination=await path_for(ctx,args['destination'],True)
    return await asyncio.to_thread(copy_bytes,source,destination,args['expected_sha256'])
async def verify_copy(args,result,ctx):
    fresh=await metadata({'path':args['destination']},ctx)
    return {'met':fresh['sha256']==args['expected_sha256'],'type':'file_state','data':fresh}

async def semantic_search(args,ctx):
    """Local lexical relevance, bounded enumeration and PDF extraction; not embeddings."""
    root=await path_for(ctx,args['path'])
    if not root.is_dir():raise NotADirectoryError(str(root))
    tokens=set(re.findall(r'\w{3,}',args['query'].casefold()))-{'the','and','about','file','paper','pdf','that','downloaded'}
    bounds=[datetime.fromisoformat(args[k]).timestamp() if args.get(k) else None for k in ('modified_after','modified_before')]
    candidates=[]; scanned=0; truncated=False
    from aries.workspace.capabilities import command
    deadline=asyncio.get_running_loop().time()+20
    for directory,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[n for n in dirs[:100] if not n.startswith('.') and not (Path(directory)/n).is_symlink()]
        for name in names:
            scanned+=1
            if scanned>1000 or len(candidates)>=50 or asyncio.get_running_loop().time()>deadline:
                truncated=True;break
            p=Path(directory)/name
            if p.is_symlink() or (args['extension'] and p.suffix.casefold()!=args['extension'].casefold()):continue
            try:
                p=await path_for(ctx,str(p)); st=p.stat()
                if not p.is_file() or st.st_size>5_000_000:continue
                if (bounds[0] is not None and st.st_mtime<bounds[0]) or (bounds[1] is not None and st.st_mtime>=bounds[1]):continue
                text='';scope='filename'
                if p.suffix.casefold() in {'.txt','.md'} and st.st_size<=100000:
                    from aries.workspace.registry import file_snapshot
                    text=(await asyncio.to_thread(file_snapshot,p))['text'][:16000];scope='filename + bounded text'
                elif p.suffix.casefold()=='.pdf':
                    # Fixed argv, no model command. No document is sent to a model.
                    code,text,_=await command(['pdftotext','-f','1','-l','8',str(p),'-'],timeout=3)
                    text=text[:16000] if code==0 else '';scope='filename + first eight PDF pages' if text else 'filename (PDF extraction unavailable)'
                filename_matches=sorted(t for t in tokens if t in name.casefold())
                text_matches=sorted(t for t in tokens if t in text.casefold())
                score=3*len(filename_matches)+len(text_matches)
                if score:
                    candidates.append({'path':str(p),'score':score,'filename_matches':filename_matches,'text_matches':text_matches,'scope':scope,'modified_at':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'size':st.st_size})
            except (OSError,ValueError,UnicodeError,TimeoutError):continue
        if truncated:break
    candidates.sort(key=lambda r:(r['score'],r['modified_at']),reverse=True)
    return {'matches':candidates[:20],'scanned':scanned,'truncated':truncated or len(candidates)>20,'method':'local lexical filename/text overlap, not calibrated semantic confidence','observed_at':datetime.now(timezone.utc).isoformat()}

async def verify_search(args,result,ctx):
    # Revalidate every returned candidate; ranking is not proof of semantic identity.
    checked=[]
    for row in result['matches']:
        fresh=await metadata({'path':row['path']},ctx)
        if fresh['size']!=row['size'] or fresh['modified_at']!=row['modified_at']:
            return {'met':False,'type':'file_candidates','data':{'reason':'Candidate changed after extraction'}}
        checked.append({**row,'sha256':fresh['sha256']})
    return {'met':True,'type':'file_candidates','data':{**result,'matches':checked}}

def register(registry):
    registry.register(Capability('file.metadata','Inspect regular file size, timestamp and SHA-256 up to 20 MB',PathInput,metadata,verify_metadata))
    registry.register(Capability('file.copy','Copy a reviewed source hash to a NEW destination; no overwrite',CopyInput,copy_file,verify_copy,effect='file_mutation',requires_approval=True))
    registry.register(Capability('file.semantic_search','Bounded local filename/PDF/text relevance with metadata filters and explanations',SemanticInput,semantic_search,verify_search,timeout_seconds=30))

class EditInput(PathInput):
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    old_text: str = Field(min_length=1,max_length=50000)
    new_text: str = Field(max_length=50000)

def edit_bytes(path,args):
    import fcntl
    with os.fdopen(open_nofollow(path,os.O_RDWR|os.O_NONBLOCK),'r+b') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        st=os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>100000:raise ValueError('Only regular text files up to 100 KB may be edited')
        raw=stream.read(100001)
        if hashlib.sha256(raw).hexdigest()!=args['expected_sha256']:raise ValueError('Approved source content changed')
        text=raw.decode('utf-8')
        if text.count(args['old_text'])!=1:raise ValueError('AMBIGUOUS: replacement must match exactly once')
        revised=text.replace(args['old_text'],args['new_text'],1).encode()
        if not revised or len(revised)>100000:raise ValueError('Edited file must be nonempty and bounded')
        stream.seek(0);stream.write(revised);stream.truncate();stream.flush();os.fsync(stream.fileno())
    return {'path':str(path),'expected_result_sha256':hashlib.sha256(revised).hexdigest()}

async def edit_file(args,ctx):
    return await asyncio.to_thread(edit_bytes,await path_for(ctx,args['path'],True),args)
async def verify_edit(args,result,ctx):
    fresh=await metadata(args,ctx)
    return {'met':fresh['sha256']==result['expected_result_sha256'],'type':'file_state','data':fresh}

def move_bytes(source,destination,expected):
    # Linux renameat2 NOREPLACE, descriptor-relative directories. No shell and
    # no overwrite fallback on unsupported/cross-filesystem moves.
    import ctypes
    import errno
    if snapshot(source)['sha256']!=expected:raise ValueError('Approved source changed')
    src_fd=open_nofollow(source.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:
        dst_fd=open_nofollow(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            libc=ctypes.CDLL(None,use_errno=True)
            rename=libc.renameat2
            rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
            rename.restype=ctypes.c_int
            if rename(src_fd,os.fsencode(source.name),dst_fd,os.fsencode(destination.name),1):
                code=ctypes.get_errno()
                raise OSError(code,os.strerror(code))
            os.fsync(src_fd);os.fsync(dst_fd)
        finally:os.close(dst_fd)
    finally:os.close(src_fd)
    return {'path':str(source),'destination':str(destination),'expected_sha256':expected}

async def move_file(args,ctx):
    return await asyncio.to_thread(move_bytes,await path_for(ctx,args['path'],True),await path_for(ctx,args['destination'],True),args['expected_sha256'])
async def verify_move(args,result,ctx):
    fresh=await metadata({'path':args['destination']},ctx)
    source=await path_for(ctx,args['path'],True)
    return {'met':not source.exists() and fresh['sha256']==args['expected_sha256'],'type':'file_state','data':{**fresh,'source_absent':not source.exists()}}

_register_reads=register

def register(registry):
    _register_reads(registry)
    registry.register(Capability('file.edit','Replace exactly one text fragment after review of source SHA-256; advisory writer lock',EditInput,edit_file,verify_edit,requires_approval=True,effect='file_mutation'))
    for name in ('move','rename'):
        registry.register(Capability('file.'+name,'Reviewed same-filesystem atomic move to a NEW path; existing destinations refused',CopyInput,move_file,verify_move,requires_approval=True,effect='file_mutation'))
