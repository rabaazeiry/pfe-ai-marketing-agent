"""BERTopic configuration, training, and metrics for the master corpus.

Phase 3.2-3.4: configures BERTopic with multilingual MiniLM embeddings, fits
on cleaned captions, and reports NPMI / Topic-Diversity / Outliers metrics.
"""
from __future__ import annotations

# Windows DLL workaround: torch MUST be imported before bertopic / transformers
# or c10.dll fails to load (WinError 1114). See project memory.
import torch  # noqa: F401

import time
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from bertopic import BERTopic
from gensim.corpora import Dictionary
from gensim.models import CoherenceModel
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP

# --- Frozen Phase 3.2 config -------------------------------------------------
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Phase 3.5: multilingual stopwords (FR + EN + AR) injected into the c-tf-idf
# CountVectorizer so high-frequency function words don't dominate topic words.
# Arabic words are built from codepoints to keep this source file pure ASCII
# (matches the convention in src/corpus/cleaner.py: no \u escapes anywhere).
# All Arabic codepoints are in the main Arabic block U+0600 - U+06FF.
# Verified by scripts/_verify_arabic_stopwords.py.
_AR_STOPWORD_CODEPOINTS = (
    (0x0641, 0x064A),                          # fi
    (0x0645, 0x0646),                          # min
    (0x0639, 0x0644, 0x0649),                  # ala
    (0x0639, 0x0646),                          # an
    (0x0627, 0x0644, 0x0649),                  # ila
    (0x0645, 0x0639),                          # maa
    (0x0647, 0x0630, 0x0627),                  # hatha
    (0x0647, 0x0630, 0x0647),                  # hathihi
    (0x0630, 0x0644, 0x0643),                  # thalik
    (0x0627, 0x0644, 0x062A, 0x064A),          # allati
    (0x0627, 0x0644, 0x0630, 0x064A),          # alladhi
    (0x0643, 0x0644),                          # kull
    (0x0645, 0x0627),                          # ma
    (0x0627, 0x0646),                          # an
    (0x0627, 0x0644),                          # al
    (0x0648,),                                 # waw
    (0x064A, 0x0627),                          # ya
    (0x0644, 0x0645),                          # lam
    (0x0644, 0x0627),                          # la
    (0x0644, 0x0643, 0x0646),                  # lakin
    (0x0627, 0x064A, 0x0636, 0x0627),          # aydan
    (0x0647, 0x0644),                          # hal
    (0x0627, 0x0645),                          # am
    (0x0625, 0x0646),                          # inna
    (0x0648, 0x0644, 0x0627),                  # wala
)

_AR_STOPWORDS = frozenset(
    "".join(chr(cp) for cp in cps) for cps in _AR_STOPWORD_CODEPOINTS
)

_FR_STOPWORDS = frozenset({
    "le", "la", "les", "de", "des", "du", "et", "est", "un", "une", "pour",
    "avec", "dans", "sur", "je", "vous", "nous", "ce", "cette", "ces", "qui",
    "que", "plus", "mais", "ou", "par", "en", "au", "aux", "à", "son", "sa",
    "ses", "mon", "ma", "mes", "notre", "votre", "tout", "toute", "tous",
    "toutes", "comme", "aussi", "fait", "ne", "pas", "non", "oui", "ici",
    "là", "déjà", "encore", "très", "bien",
})

_EN_STOPWORDS = frozenset({
    "the", "and", "of", "to", "a", "in", "is", "you", "that", "it", "for",
    "on", "with", "this", "are", "as", "be", "at", "by", "from", "we", "our",
    "your", "my", "have", "has", "will", "can", "all", "an", "was", "were",
    "been", "being", "do", "does", "did", "but", "or", "if", "then", "so",
    "than",
})

STOPWORDS_MULTILINGUAL = _FR_STOPWORDS | _EN_STOPWORDS | _AR_STOPWORDS

UMAP_KWARGS = dict(
    n_neighbors=15,
    n_components=5,
    min_dist=0.0,
    metric="cosine",
    random_state=42,
)

HDBSCAN_KWARGS = dict(
    min_cluster_size=30,
    min_samples=5,
    metric="euclidean",
    cluster_selection_method="eom",
    prediction_data=True,
)

VECTORIZER_KWARGS = dict(
    ngram_range=(1, 2),
    max_features=10000,
    stop_words=list(STOPWORDS_MULTILINGUAL),
)

TOP_N_WORDS = 10

# Phase 3.4 acceptance targets
TARGETS = {
    "npmi": 0.15,
    "diversity": 0.70,
    "outliers_max": 0.30,
}


def build_topic_model() -> BERTopic:
    """Return a configured (untrained) BERTopic instance."""
    embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return BERTopic(
        embedding_model=embedder,
        umap_model=UMAP(**UMAP_KWARGS),
        hdbscan_model=HDBSCAN(**HDBSCAN_KWARGS),
        vectorizer_model=CountVectorizer(**VECTORIZER_KWARGS),
        nr_topics="auto",
        top_n_words=TOP_N_WORDS,
        verbose=True,
    )


def reduce_outliers_post_train(
    model: BERTopic,
    docs: List[str],
    topics: List[int],
    *,
    strategy: str = "c-tf-idf",
    threshold: float = 0.3,
) -> List[int]:
    """Re-assign HDBSCAN outliers (-1) to nearest topic via c-tf-idf similarity.

    Refreshes the model's internal c-tf-idf representation so `model.get_topic(...)`
    reflects the post-reduction document membership.

    NOTE: BERTopic's `update_topics()` will silently overwrite
    `self.vectorizer_model` with a fresh default `CountVectorizer` unless one
    is passed explicitly — that wipes out our multilingual stop_words + (1,2)
    ngram config. We pass the existing vectorizer back in to preserve it.
    """
    new_topics = model.reduce_outliers(
        documents=docs,
        topics=topics,
        strategy=strategy,
        threshold=threshold,
    )
    model.update_topics(
        docs,
        topics=new_topics,
        vectorizer_model=model.vectorizer_model,
    )
    return list(new_topics)


def _snapshot_topic_words(
    model: BERTopic,
    topics: List[int],
) -> Dict[int, List[str]]:
    """Capture top-N words per (non-outlier) topic from the model's CURRENT state."""
    return {
        int(tid): [w for w, _ in model.get_topic(tid)][:TOP_N_WORDS]
        for tid in set(topics)
        if tid != -1
    }


def train_topic_model(
    df: pd.DataFrame,
    text_column: str = "caption_clean",
) -> Tuple[
    BERTopic,
    List[int],
    Dict[int, List[str]],
    List[int],
    np.ndarray,
    pd.DataFrame,
    float,
]:
    """Fit BERTopic, snapshot pre-reduction topic words, then reduce outliers.

    Returns ``(model, topics_before, topic_words_before, topics_after, probs,
    df_out, elapsed_s)``. ``df_out['topic_id']`` carries the reduced
    assignments. ``topic_words_before`` is the per-topic top-N word list
    captured immediately after fit, so metrics computed on the BEFORE state
    reflect the pre-`update_topics` representation.

    ``text_column`` selects which df column carries the documents (default
    ``"caption_clean"``; v2 brand-masked training uses ``"caption_masked"``).
    """
    docs = df[text_column].tolist()
    model = build_topic_model()
    t0 = time.perf_counter()
    topics_before, probs = model.fit_transform(docs)
    topic_words_before = _snapshot_topic_words(model, list(topics_before))
    topics_after = reduce_outliers_post_train(model, docs, topics_before)
    elapsed = time.perf_counter() - t0
    df_out = df.copy()
    df_out["topic_id"] = topics_after
    return (
        model,
        list(topics_before),
        topic_words_before,
        topics_after,
        probs,
        df_out,
        elapsed,
    )


def compute_metrics(
    model: BERTopic,
    docs: List[str],
    topics: List[int],
    topic_words_override: Dict[int, List[str]] | None = None,
) -> Dict[str, Any]:
    """Compute NPMI coherence, topic diversity, and outlier stats.

    If ``topic_words_override`` is provided, the per-topic top-N word lists
    are read from that dict instead of from ``model.get_topic(...)``. Use this
    when the model state has since been mutated (e.g. by ``update_topics``)
    but you want metrics that reflect an earlier snapshot.
    """
    topics_arr = np.asarray(topics)
    n_total = len(topics_arr)
    n_outliers = int((topics_arr == -1).sum())
    unique_topics = sorted(t for t in set(topics) if t != -1)

    # Per-topic top-N words (non-outlier topics only).
    topic_word_lists: List[List[str]] = []
    for tid in unique_topics:
        if topic_words_override is not None and tid in topic_words_override:
            words = topic_words_override[tid][:TOP_N_WORDS]
        else:
            words = [w for w, _ in model.get_topic(tid)][:TOP_N_WORDS]
        topic_word_lists.append(words)

    # NPMI coherence — tokenize with the same regex CountVectorizer used at fit-time.
    tokenizer = CountVectorizer().build_tokenizer()
    tokenized_docs = [tokenizer(d) for d in docs]
    npmi: float
    try:
        if not topic_word_lists:
            raise ValueError("no non-outlier topics")
        dictionary = Dictionary(tokenized_docs)
        cm = CoherenceModel(
            topics=topic_word_lists,
            texts=tokenized_docs,
            dictionary=dictionary,
            coherence="c_npmi",
        )
        npmi = float(cm.get_coherence())
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] NPMI computation failed: {exc}")
        npmi = float("nan")

    # Topic diversity (Dieng et al. 2020): unique top-words / total slots.
    flat = [w for words in topic_word_lists for w in words]
    diversity = (len(set(flat)) / len(flat)) if flat else 0.0

    return {
        "n_topics":        len(unique_topics),
        "outliers_count":  n_outliers,
        "outliers_ratio":  n_outliers / n_total if n_total else 0.0,
        "npmi_coherence":  npmi,
        "topic_diversity": diversity,
    }
