import os
import re
import math
import json
from pathlib import Path
from typing import List, Tuple, Dict, Any
from src.models import RAGDocument
from src.config import DATA_DIR

INDEX_FILE = DATA_DIR / "vector_store" / "index.json"

class LocalVectorStore:
    """
    A lightweight, high-performance hybrid vector store supporting TF-IDF
    and BM25 scoring for instant local retrieval without remote API latencies.
    """
    def __init__(self):
        self.documents: Dict[str, RAGDocument] = {}
        self.doc_term_freqs: Dict[str, Dict[str, int]] = {}
        self.idf: Dict[str, float] = {}
        self.avg_doc_len: float = 0.0
        self.load()

    def tokenize(self, text: str) -> List[str]:
        cleaned = re.sub(r"[^a-zA-Z0-9+#.\-_/]", " ", text.lower())
        tokens = cleaned.split()
        return [t for t in tokens if len(t) > 1]

    def add_documents(self, docs: List[RAGDocument]):
        for doc in docs:
            self.documents[doc.doc_id] = doc
        self._rebuild_index()
        self.save()

    def _rebuild_index(self):
        self.doc_term_freqs.clear()
        total_len = 0
        df: Dict[str, int] = {}
        N = len(self.documents)

        for doc_id, doc in self.documents.items():
            combined_text = f"{doc.title} {doc.content}"
            tokens = self.tokenize(combined_text)
            total_len += len(tokens)
            
            tf: Dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            self.doc_term_freqs[doc_id] = tf

            for t in tf.keys():
                df[t] = df.get(t, 0) + 1

        self.avg_doc_len = (total_len / N) if N > 0 else 1.0
        self.idf.clear()
        for term, freq in df.items():
            self.idf[term] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[RAGDocument, float]]:
        """BM25 search over ingested documents."""
        q_tokens = self.tokenize(query)
        if not q_tokens or not self.documents:
            return []

        k1 = 1.5
        b = 0.75
        scores: List[Tuple[RAGDocument, float]] = []

        for doc_id, doc in self.documents.items():
            tf = self.doc_term_freqs.get(doc_id, {})
            doc_len = sum(tf.values())
            score = 0.0

            for q in q_tokens:
                if q in tf:
                    term_freq = tf[q]
                    idf = self.idf.get(q, 0.1)
                    numerator = term_freq * (k1 + 1)
                    denominator = term_freq + k1 * (1 - b + b * (doc_len / (self.avg_doc_len or 1.0)))
                    score += idf * (numerator / denominator)

            if score > 0:
                scores.append((doc, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def match_job(self, title: str, description: str, skills_list: List[str]) -> Tuple[float, List[str], str]:
        """Calculates match score between candidate profile and a job posting."""
        combined_job = f"{title} {description}"
        job_tokens = set(self.tokenize(combined_job))

        matched_skills = []
        for s in skills_list:
            clean_s = s.lower().strip()
            if clean_s in job_tokens or any(re.search(r'\b' + re.escape(clean_s) + r'\b', combined_job, re.I) for _ in [1]):
                matched_skills.append(s)

        # Retrieve top relevant context from resume/GitHub
        top_docs = self.search(f"{title} {' '.join(matched_skills)}", top_k=3)
        relevant_context = "\n---\n".join([f"[{d.title}]:\n{d.content[:400]}" for d, _ in top_docs])

        # Scoring heuristic
        skill_ratio = (len(matched_skills) / max(len(skills_list) * 0.4, 1.0))
        skill_score = min(skill_ratio, 1.0) * 0.7
        bm25_bonus = 0.3 if len(top_docs) > 0 else 0.0
        final_score = round(min(skill_score + bm25_bonus, 0.99), 2)

        return final_score, matched_skills, relevant_context

    def save(self):
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "docs": [doc.model_dump() for doc in self.documents.values()]
        }
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self):
        if INDEX_FILE.exists():
            try:
                with open(INDEX_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("docs", []):
                        doc = RAGDocument(**item)
                        self.documents[doc.doc_id] = doc
                    self._rebuild_index()
            except Exception as e:
                print(f"[Warning] Could not load vector index: {e}")
