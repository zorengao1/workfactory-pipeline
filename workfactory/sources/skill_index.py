"""Local embedding recall over a prebuilt skill index. Skills are source data, never executed.

The index is built offline (scripts/export_skill_index.py) and holds skill vectors,
precomputed O*NET occupation query vectors and a SQLite table with skill bodies.
Recall only nominates candidates; relevance is decided by the model review that follows.
"""
import hashlib
import json
import sqlite3
import threading
from pathlib import Path

FILES = ('manifest.json', 'skills.f16.npy', 'skills.ids.json', 'queries.f16.npy',
         'queries.ids.json', 'skills.sqlite')
_CACHE = {}
_LOCK = threading.Lock()


class SkillIndexError(ValueError):
    pass


def numpy():
    try:
        import numpy
    except ImportError:
        raise SkillIndexError('Local skill index needs numpy on the controller; install numpy '
                              'or disable skill_discovery. No other backend is selected automatically.') from None
    return numpy


KEYS = ('skill_id', 'name', 'description', 'source', 'repo', 'url', 'n_words', 'attachments',
        'attachments_missing', 'body')


def database(folder):
    path = Path(folder).resolve() / 'skills.sqlite'
    if not path.is_file():
        raise SkillIndexError('Skill index missing at ' + str(path.parent) + '; export it before building or running skill routes')
    return sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)


def read_documents(folder, skill_ids):
    """Skill bodies by id. Needs only the SQLite file, not the vectors."""
    skill_ids = list(skill_ids)
    if not skill_ids:
        return {}
    db = database(folder)
    try:
        rows = []
        for start in range(0, len(skill_ids), 500):
            part = skill_ids[start:start + 500]
            rows += db.execute('SELECT ' + ','.join(KEYS) + ' FROM skills WHERE skill_id IN (' + ','.join('?' * len(part)) + ')', part).fetchall()
    finally:
        db.close()
    return {row[0]: dict(zip(KEYS, row)) for row in rows}


def material(doc, **extra):
    return dict(source_id='skill-' + doc['skill_id'], id=doc['skill_id'], name=doc['name'], description=doc['description'],
                url=doc['url'] or 'skill-index:' + doc['source'] + ':' + doc['repo'],
                provenance=doc['source'] + ':' + doc['repo'], content=doc['body'],
                sha256=hashlib.sha256(doc['body'].encode()).hexdigest(),
                attachments=doc['attachments'], attachments_missing=bool(doc['attachments_missing']), **extra)


def sample_anchors(folder, count, seed, min_words=200, max_words=4000):
    """Seeded anchors for the single-skill route: self-contained skills, round-robin over repositories."""
    import random
    db = database(folder)
    try:
        rows = db.execute("SELECT skill_id, source || ':' || repo FROM skills WHERE n_words BETWEEN ? AND ? "
                          "AND attachments_missing=0 AND name<>'' AND description<>'' ORDER BY skill_id",
                          (min_words, max_words)).fetchall()
    finally:
        db.close()
    groups = {}
    for sid, repo in rows:
        groups.setdefault(repo, []).append(sid)
    rng = random.Random(seed)
    order = sorted(groups)
    rng.shuffle(order)
    queues = [rng.sample(groups[r], len(groups[r])) for r in order]
    picked = []
    depth = 0
    while len(picked) < count and any(depth < len(q) for q in queues):
        picked += [q[depth] for q in queues if depth < len(q)]
        depth += 1
    if len(picked) < count:
        raise SkillIndexError('Only ' + str(len(picked)) + ' eligible anchor skills in index')
    return picked[:count]


class SkillIndex:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        missing = [name for name in FILES if not (self.folder / name).is_file()]
        if missing:
            raise SkillIndexError('Skill index incomplete at ' + str(self.folder) + ' missing ' + ', '.join(missing))
        self.manifest = json.loads((self.folder / 'manifest.json').read_text())
        self.skill_ids = json.loads((self.folder / 'skills.ids.json').read_text())
        query_ids = json.loads((self.folder / 'queries.ids.json').read_text())
        np = numpy()
        # float32 once: float16 products are slow and the matrix is shared by all task threads.
        self.skills = np.load(self.folder / 'skills.f16.npy', mmap_mode='r').astype(np.float32)
        self.queries = np.load(self.folder / 'queries.f16.npy', mmap_mode='r')
        if (self.skills.shape[0] != len(self.skill_ids) or self.queries.shape[0] != len(query_ids)
                or self.skills.shape[1] != self.queries.shape[1]
                or self.manifest.get('skills') != len(self.skill_ids)
                or self.manifest.get('queries') != len(query_ids)):
            raise SkillIndexError('Skill index vectors, ids and manifest disagree; rebuild the index')
        self.by_occupation = {}
        for row, key in enumerate(query_ids):
            self.by_occupation.setdefault(key.split('|', 1)[0], []).append((row, key))
        self.identity = dict(index_id=self.manifest.get('index_id'), model=self.manifest.get('embedding_model'),
                             skills=len(self.skill_ids), queries=len(query_ids))

    def documents(self, skill_ids):
        return read_documents(self.folder, skill_ids)

    def candidates(self, onet_code, limit, per_query=8, min_similarity=0.4, min_words=50,
                   max_words=4000, exclude=()):
        """Round-robin the best skills of the occupation profile and each task statement."""
        np = numpy()
        rows = self.by_occupation.get(onet_code)
        if not rows:
            raise SkillIndexError('Occupation has no precomputed query vectors ' + str(onet_code))
        vectors = np.asarray(self.queries[[row for row, _ in rows]], dtype=np.float32)
        scores = vectors @ self.skills.T
        width = min(per_query + len(exclude) + 8, scores.shape[1])
        part = np.argpartition(-scores, width - 1, axis=1)[:, :width]
        ranked = []
        for q in range(scores.shape[0]):
            order = part[q][np.argsort(-scores[q][part[q]])]
            ranked.append([(float(scores[q][j]), int(j)) for j in order if scores[q][j] >= min_similarity])
        # Strongest query first, so the best evidence leads each round.
        queues = sorted(zip(ranked, rows), key=lambda item: -(item[0][0][0] if item[0] else 0))
        skipped = set(exclude)
        chosen = {}
        for rank in range(width):
            batch = [(q[rank], key) for q, (_, key) in queues if rank < len(q)]
            fresh = [self.skill_ids[j] for (_, j), _ in batch
                     if self.skill_ids[j] not in chosen and self.skill_ids[j] not in skipped]
            docs = self.documents(sorted(set(fresh)))
            for (score, j), key in batch:
                sid = self.skill_ids[j]
                if sid in skipped:
                    continue
                if sid in chosen:
                    chosen[sid]['matched_queries'].append(key)
                    continue
                doc = docs.get(sid)
                if not doc or not min_words <= doc['n_words'] <= max_words:
                    skipped.add(sid)
                    continue
                if len(chosen) >= limit:
                    continue
                chosen[sid] = material(doc, similarity=round(score, 4), matched_queries=[key])
            if len(chosen) >= limit:
                break
        return list(chosen.values())

    def neighbors(self, skill_id, limit, min_similarity=0.5, max_similarity=0.85, min_words=50,
                  max_words=4000, exclude=()):
        """Related skills of an anchor that are neither its variants nor variants of each other."""
        np = numpy()
        if not hasattr(self, 'rows'):
            self.rows = {sid: n for n, sid in enumerate(self.skill_ids)}
        if skill_id not in self.rows:
            raise SkillIndexError('Anchor skill not in index ' + str(skill_id))
        scores = self.skills @ self.skills[self.rows[skill_id]]
        skipped = set(exclude) | {skill_id}
        band = np.flatnonzero((scores >= min_similarity) & (scores < max_similarity))
        band = band[np.argsort(-scores[band])][:limit * 20 + len(skipped)]
        pool = [(float(scores[j]), int(j)) for j in band if self.skill_ids[int(j)] not in skipped]
        docs = self.documents([self.skill_ids[j] for _, j in pool])
        found, rows = [], []
        for score, j in pool:
            doc = docs.get(self.skill_ids[j])
            if not doc or not min_words <= doc['n_words'] <= max_words:
                continue
            # Variants of one already chosen skill add nothing to compose with.
            if rows and float((self.skills[rows] @ self.skills[j]).max()) >= max_similarity:
                continue
            rows.append(j)
            found.append(material(doc, similarity=round(score, 4), matched_queries=['anchor:' + skill_id]))
            if len(found) >= limit:
                break
        return found


def load_index(folder):
    key = str(Path(folder).resolve())
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = SkillIndex(key)
        return _CACHE[key]
