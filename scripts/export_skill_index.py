"""Package a cleaned skill table and its embeddings into the local index the pipeline reads.

Runs offline in a data environment with numpy and pyarrow. Nothing is downloaded or executed.
Inputs are the outputs of the skill pool preparation: one row per skill and row-aligned vectors.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ('skill_id', 'name', 'description', 'source', 'repo', 'url', 'path', 'n_words',
           'attachments', 'attachments_missing', 'body')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skills', required=True, help='Parquet table with ' + ', '.join(COLUMNS))
    p.add_argument('--skill-vectors', required=True)
    p.add_argument('--skill-ids', required=True)
    p.add_argument('--query-vectors', required=True, help='O*NET profile and task vectors')
    p.add_argument('--query-ids', required=True, help='JSON list of code|profile and code|task|n')
    p.add_argument('--embedding-model', required=True)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    import numpy as np
    import pyarrow.parquet as pq
    if a.output.exists():
        raise SystemExit('Output exists; choose a new directory so an index in use is never rewritten')
    skill_ids = json.loads(Path(a.skill_ids).read_text())
    query_ids = json.loads(Path(a.query_ids).read_text())
    skills = np.load(a.skill_vectors, mmap_mode='r')
    queries = np.load(a.query_vectors, mmap_mode='r')
    if skills.shape[0] != len(skill_ids) or queries.shape[0] != len(query_ids) or skills.shape[1] != queries.shape[1]:
        raise SystemExit('Vectors and ids disagree')
    if len(set(skill_ids)) != len(skill_ids) or len(set(query_ids)) != len(query_ids):
        raise SystemExit('Duplicate ids')
    for sample in (skills[:256], queries[:256]):
        if abs(float(np.linalg.norm(np.asarray(sample, dtype=np.float32), axis=1).mean()) - 1) > 0.01:
            raise SystemExit('Vectors must be L2-normalized')
    table = pq.read_table(a.skills, columns=list(COLUMNS)).to_pylist()
    if {r['skill_id'] for r in table} != set(skill_ids):
        raise SystemExit('Skill table and vector ids differ')
    a.output.mkdir(parents=True)
    db = sqlite3.connect(a.output / 'skills.sqlite')
    db.execute('CREATE TABLE skills (skill_id TEXT PRIMARY KEY, name TEXT, description TEXT, source TEXT, repo TEXT,'
               ' url TEXT, path TEXT, n_words INTEGER, attachments TEXT, attachments_missing INTEGER, body TEXT)')
    db.executemany('INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   [tuple(int(r[c]) if c in ('n_words', 'attachments_missing') else (r[c] or '') for c in COLUMNS) for r in table])
    db.commit()
    db.close()
    np.save(a.output / 'skills.f16.npy', np.asarray(skills, dtype=np.float16))
    np.save(a.output / 'queries.f16.npy', np.asarray(queries, dtype=np.float16))
    (a.output / 'skills.ids.json').write_text(json.dumps(skill_ids))
    (a.output / 'queries.ids.json').write_text(json.dumps(query_ids))
    digest = hashlib.sha256(('\n'.join(skill_ids) + '\n' + '\n'.join(query_ids) + '\n' + a.embedding_model).encode()).hexdigest()
    sources = {}
    for r in table:
        sources[r['source']] = sources.get(r['source'], 0) + 1
    (a.output / 'manifest.json').write_text(json.dumps(dict(
        index_id=digest[:16], embedding_model=a.embedding_model, dimension=int(skills.shape[1]),
        skills=len(skill_ids), queries=len(query_ids), occupations=len({q.split('|')[0] for q in query_ids}),
        skills_by_source=sources, created_at=datetime.now(timezone.utc).isoformat(),
        inputs=dict(skills=str(a.skills), skill_vectors=str(a.skill_vectors), query_vectors=str(a.query_vectors)),
        note='Recall nominates candidates only; relevance is judged by the model at run time.'), indent=2) + '\n')
    print('Index written', a.output, 'skills', len(skill_ids), 'queries', len(query_ids), 'id', digest[:16])


if __name__ == '__main__':
    main()
