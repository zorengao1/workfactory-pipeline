"""Frozen artifact access and verifiable reuse across planning and construction."""
import hashlib
import shutil
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifacts(materials):
    result = {}
    for source in materials:
        if not source.get('snapshot'):
            continue
        path = Path(source['snapshot']).resolve()
        if not path.is_file():
            raise ValueError('Missing source snapshot ' + source['source_id'])
        actual = digest(path)
        if source.get('sha256') and source['sha256'] != actual:
            raise ValueError('Source snapshot hash mismatch ' + source['source_id'])
        text = Path(source['full_text_path']) if source.get('full_text_path') else path.with_suffix('.txt')
        if source.get('full_text_sha256') and (not text.is_file() or digest(text)!=source['full_text_sha256']):
            raise ValueError('Full text hash mismatch '+source['source_id'])
        result[source['source_id']] = {
            'source_id':source['source_id'], 'path':str(path), 'sha256':actual,
            'text_path':str(text) if text.is_file() else None,
            'total_characters':len(text.read_text()) if text.is_file() else None,
            'full_text_available':text.is_file(),
            'format':'pdf' if path.read_bytes().startswith(b'%PDF-') else path.suffix.lstrip('.'),
            'provenance':source.get('provenance',''),
            'excerpt':source.get('content',''),
        }
    return result


def read_source(catalog, source_id, start=0, length=12000):
    item = catalog[source_id]
    if not isinstance(start,int) or start < 0 or not isinstance(length,int) or not 1 <= length <= 20000:
        raise ValueError('Invalid text range')
    if item['text_path'] is None:
        raise ValueError('Full extracted text unavailable; cannot claim full document access')
    body = Path(item['text_path']).read_text()
    return {'source_id':source_id,'start':start,'end':min(start+length,len(body)),
            'total_characters':len(body),'text':body[start:start+length],
            'scope':'extracted text only; tables or images may require builder inspection'}


def binding_errors(plan, catalog):
    errors=[]
    for item in plan['reference_files']:
        if item['method'] not in ('reuse','adapt'):
            continue
        ids=item.get('source_ids',[])
        if not ids or any(i not in catalog for i in ids):
            errors.append('reuse/adapt needs frozen source_ids ' + item['id'])
        elif item['method']=='reuse' and (len(ids)!=1 or item['format'].lower()!=catalog[ids[0]]['format']):
            errors.append('reuse must preserve one original file and format ' + item['id'])
    return errors


def stage_reuse(plan, materials, root):
    catalog=artifacts(materials)
    errors=binding_errors(plan,catalog)
    if errors: raise ValueError('; '.join(errors))
    records=[];root=Path(root).resolve()
    for item in plan['reference_files']:
        if item['method']!='reuse':continue
        source=catalog[item['source_ids'][0]]
        target=(root/item['path']).resolve()
        if not target.is_relative_to(root/'inputs'):
            raise ValueError('Reuse destination must be under inputs')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source['path'],target)
        records.append({'file_id':item['id'],'source_id':source['source_id'],
                        'path':item['path'],'sha256':source['sha256']})
    return records


def verify_reuse(records, root):
    return all((Path(root)/r['path']).is_file() and digest(Path(root)/r['path'])==r['sha256'] for r in records)


def text_metadata(path, body):
    """Keep full extraction both on disk and in model input."""
    path=Path(path)
    path.write_text(body)
    return {'content':body, 'content_is_preview':False,
            'full_text_path':str(path.resolve()), 'full_text_sha256':digest(path),
            'extraction_total_characters':len(body), 'extraction_truncated':False}


def search_source(catalog, source_id, query, start=0, limit=10):
    if not isinstance(query,str) or not query.strip() or not isinstance(start,int) or start<0 or not isinstance(limit,int) or not 1<=limit<=20:
        raise ValueError('Invalid search arguments')
    item=catalog[source_id]
    if not item['text_path']:
        raise ValueError('Full extracted text unavailable')
    body=Path(item['text_path']).read_text();hits=[];cursor=start
    while len(hits)<limit:
        pos=body.find(query,cursor)
        if pos<0:break
        lo=max(0,pos-150);hi=min(len(body),pos+len(query)+250)
        hits.append({'match_start':pos,'start':lo,'end':hi,'text':body[lo:hi]})
        cursor=pos+len(query)
    return {'source_id':source_id,'matches':hits,'next_start':cursor if len(hits)==limit else None,
            'total_characters':len(body),'matching':'case-sensitive literal text','scope':'extracted text only'}


def full_text_inputs(inputs):
    """Restore legacy previews before intent generation/review; never modify sources."""
    import copy
    result = copy.deepcopy(inputs)
    materials = result.get('source_materials', [])
    catalog = artifacts(materials)
    for source in materials:
        sid = source.get('source_id')
        path = source.get('full_text_path') or catalog.get(sid, {}).get('text_path')
        if path:
            path = Path(path)
            if not path.is_file():
                raise ValueError('Missing full source text ' + str(sid))
            if source.get('full_text_sha256') and digest(path) != source['full_text_sha256']:
                raise ValueError('Full text hash mismatch ' + str(sid))
            body = path.read_text()
            source.update(content=body, content_is_preview=False,
                          extraction_total_characters=len(body), extraction_truncated=False)
        elif source.get('content_is_preview') or source.get('extraction_truncated'):
            raise ValueError('Full source text required for intent stage ' + str(sid))
    return result
