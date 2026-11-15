"""Compare GeNAIus BM25 with rank_bm25.BM25Okapi on the committed 503-chunk corpus (same tokenizer).

One-off Görev 056 measurement; needs `pip install rank-bm25==0.2.2` (not a project dependency).
Usage: python scripts/dev/bm25_library_comparison.py <repo_root> <out.json>
"""
import json, sys
from pathlib import Path
root = Path(sys.argv[1]); sys.path.insert(0, str(root / "src"))
from genaius.retrieval.bm25 import BM25Index, tokenize_text
from genaius.retrieval.documents import DocumentChunk
from rank_bm25 import BM25Okapi

raw = json.loads((root / "data/processed/psi_document_chunks.json").read_text())["chunks"]
chunks = []
for c in raw:
    c = dict(c)
    for k in ("section_path", "printed_pages", "extraction_warnings"):
        c[k] = tuple(c.get(k) or ())
    chunks.append(DocumentChunk(**{k: c[k] for k in DocumentChunk.__dataclass_fields__ if k in c}))
ours = BM25Index(chunks)
docs = [tokenize_text(f"{ch.section_number or ''} {ch.section_title}\n{ch.source_text}") for ch in chunks]
lib = BM25Okapi(docs, k1=ours.k1, b=ours.b)
cases = json.loads((root / "tests/evaluation/eval_cases.json").read_text())["cases"]
queries = [c["request"]["query"] for c in cases if c.get("request", {}).get("query")]
queries += ["What is the burning rate unit in PSI-69?", "extinction diameter heptane", "cool flame n-heptane",
            "helium diluent extinction", "BASS-II flow restrictor flammability", "PMMA sphere oxygen concentration",
            "carbon dioxide dilution methanol", "radiative extinction large droplets", "burning rate pressure dependence",
            "smoldering cotton", "spread rate thin fuel", "flame standoff ratio"]
K = 5
rows, overlap, top1, kend = [], 0, 0, []
for q in queries:
    toks = list(dict.fromkeys(tokenize_text(q)))
    if not toks:
        continue
    a = [h.chunk_id for h in ours.search(q, top_k=K, use_bilingual_aliases=False).hits]
    s = lib.get_scores(toks)
    order = sorted(range(len(chunks)), key=lambda i: (-round(s[i], 12), chunks[i].document_id, chunks[i].chunk_ordinal, chunks[i].chunk_id))
    b = [chunks[i].chunk_id for i in order[:K] if s[i] > 0]
    ov = len(set(a) & set(b)); overlap += ov; top1 += bool(a and b and a[0] == b[0])
    rows.append({"query": q, "ours_top5": a, "rank_bm25_top5": b, "overlap": ov, "same_order": a == b})
n = len(rows)
summary = {"chunks": len(chunks), "queries": n, "mean_top5_overlap": round(overlap / (n * K), 3),
           "top1_agreement": f"{top1}/{n}", "identical_top5_order": f"{sum(r['same_order'] for r in rows)}/{n}"}
print(json.dumps(summary))
Path(sys.argv[2]).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
