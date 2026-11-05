"""The corpus that explanations cite: the official documents the validator's rules come from,
passage by passage, each with the days it applies (ADR-0020).

- :mod:`sef_api.rag.text`: Serbian in two scripts, and text folded for search;
- :mod:`sef_api.rag.corpus`: the corpus's files, and its passages over time;
- :mod:`sef_api.rag.embeddings`: the vectors by which passages are found by meaning;
- :mod:`sef_api.rag.ingest`: loading the corpus into the database;
- :mod:`sef_api.rag.citations`: the passages each rule is authored from.
"""
