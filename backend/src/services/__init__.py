"""
Services Module
Hosts HTTP-agnostic application services (e.g. the RAG pipeline) that can be
constructed via dependency injection and reused outside a FastAPI request
context (notably by the Phase 6 RAGAS evaluation harness).
"""
