"""
RAG pipeline service.

Hosts the full Retrieval-Augmented Generation pipeline (embed -> vector
search -> fuzzy filename pre-include -> dynamic source filter -> confidence
scoring -> LLM generation) as a framework-agnostic RagService class.

Extracted verbatim from backend/src/api/endpoints/chat.py (DEBT-01) so the
pipeline can be invoked directly -- notably by the Phase 6 RAGAS evaluation
harness -- without going through HTTP. This module imports NOTHING from
FastAPI.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import logging

import numpy as np
from rapidfuzz import fuzz

from src.database.repository import DocumentRepository
from src.llm_interface.implementations.mistral_api import MistralAPIService
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.monitoring.rag_debug_logger import RagDebugService
from src.cost.budget_guard import BudgetGuard, BudgetReservation
from src.cost.usage_tracker import UsageTracker
from src.config import settings

logger = logging.getLogger(__name__)

# System prompt template for RAG context-based responses (moved from chat.py)
MIMIR_SYSTEM_PROMPT = """Vous êtes Mimir, un assistant documentaire intelligent.
Votre rôle est de répondre aux questions en vous basant UNIQUEMENT sur le contexte documentaire fourni.

Règles importantes:
1. Répondez UNIQUEMENT avec les informations présentes dans le contexte
2. Si la réponse n'est pas dans le contexte, dites-le clairement
3. Soyez précis et factuel
4. Utilisez un ton professionnel mais accessible

Contexte documentaire:
{context}

Répondez à la question suivante en vous basant sur ce contexte:"""


def _clean_filename(filename: str) -> str:
    """
    Clean the filename to extract a human-readable name.
    Removes the hash, extension and underscores.

    Example: "2e821c8cd63bcacaca47f4f52576ff08fadbad66dde9e359a3fbae80da79a818_CV_Yann_POINTUD.pdf"
            -> "CV Yann POINTUD"
    """
    import os

    # Remove the path if present
    filename = os.path.basename(filename)

    # Remove the extension
    filename = os.path.splitext(filename)[0]

    # Remove the hash (64 hex characters at the beginning)
    if '_' in filename and len(filename.split('_')[0]) == 64:
        filename = '_'.join(filename.split('_')[1:])

    # Replace underscores with spaces
    filename = filename.replace('_', ' ')

    return filename.strip()


def _find_documents_by_fuzzy_match(question: str, document_repository, threshold: int = 70) -> List[tuple]:
    """
    Find documents whose filename matches the question via fuzzy matching.

    Args:
        question: The user question
        document_repository: Document repository
        threshold: Minimum fuzzy score threshold (0-100)

    Returns:
        List of tuples (document_id, filename, fuzzy_score)
    """
    all_documents = document_repository.get_all()
    matches = []

    for doc in all_documents:
        # Clean the filename
        clean_name = _clean_filename(doc.filename)

        # Calculate the fuzzy matching score
        fuzzy_score = fuzz.partial_ratio(question.lower(), clean_name.lower())

        if fuzzy_score >= threshold:
            matches.append((doc.id, doc.filename, fuzzy_score))
            logger.info(f"Fuzzy match found: '{clean_name}' (score: {fuzzy_score}) for question: '{question}'")

    # Sort by descending score
    matches.sort(key=lambda x: x[2], reverse=True)

    return matches


async def _pre_include_document_chunks(
    document_ids: List[int],
    question_embedding: List[float],
    vector_store,
    document_repository,
    boost_factor: float,
    filename_similarities: Dict[int, float]
) -> List[Any]:
    """
    Retrieve all chunks from specified documents and apply the boost.

    Args:
        document_ids: IDs of documents to pre-include
        question_embedding: Question embedding vector
        vector_store: The FAISS vector store
        document_repository: Document repository
        boost_factor: Boost factor to apply
        filename_similarities: Dictionary {document_id: fuzzy_score}

    Returns:
        List of chunks with boosted scores
    """
    pre_included_chunks = []

    for doc_id in document_ids:
        # Retrieve the document
        document = document_repository.get_by_id(doc_id)
        if not document:
            continue

        # Retrieve all chunks for this document from FAISS
        # Perform a search with a very large top_k and filter by document_id
        all_results = await asyncio.to_thread(vector_store.query, question_embedding, top_k=1000)

        # Filter to keep only chunks from this document
        doc_chunks = [r for r in all_results if int(r.document_id) == doc_id]

        # Apply boost to each chunk
        filename_similarity = filename_similarities.get(doc_id, 0) / 100.0  # Normalize 0-1

        for chunk in doc_chunks:
            # Calculate boost based on filename similarity
            original_score = chunk.similarity_score
            boost_amount = boost_factor * filename_similarity
            boosted_score = chunk.similarity_score + boost_amount
            boosted_score = min(0.99, boosted_score)

            # Update the score
            chunk.similarity_score = boosted_score
            pre_included_chunks.append(chunk)

            # Report the true pre-boost score: chunk.similarity_score has already
            # been reassigned to the (possibly clamped) boosted value, so it can
            # no longer be reversed by subtracting boost_amount.
            logger.debug(f"Pre-included chunk: doc_id={doc_id}, chunk_index={chunk.chunk_index}, "
                        f"score_original={original_score:.3f}, "
                        f"boost={boost_amount:.3f}, score_final={boosted_score:.3f}")

    return pre_included_chunks


def _calculate_weighted_confidence(search_results: List[Any], algorithm: str = "weighted") -> float:
    """
    Calculate confidence score using different algorithms.

    Args:
        search_results: List of search results
        algorithm: "simple" or "weighted"

    Returns:
        Confidence score between 0.0 and 0.95
    """
    if not search_results:
        return 0.1

    scores = [r.similarity_score for r in search_results]

    if algorithm == "simple":
        # Original algorithm (for backward compatibility)
        avg_similarity = sum(scores) / len(scores)
        return min(0.9, avg_similarity * (len(search_results) / 5))

    elif algorithm == "weighted":
        # Improved algorithm with degressive weighting

        # 1. Position-weighted score (first results count more)
        weights = [1.0, 0.8, 0.6, 0.4, 0.2]  # Degressive weighting
        weighted_sum = sum(
            score * weights[min(i, len(weights)-1)]
            for i, score in enumerate(scores)
        )
        weight_total = sum(weights[:min(len(scores), len(weights))])
        base_score = weighted_sum / weight_total

        # 2. Coherence factor (penalizes highly dispersed scores)
        if len(scores) > 1:
            std_dev = np.std(scores)
            max_score = max(scores)
            # High coherence if standard deviation is low relative to max
            coherence_factor = max(0.5, 1 - (std_dev / max(max_score, 0.1)))
        else:
            coherence_factor = 1.0

        # 3. Quality factor (bonus if the best score is really good)
        best_score = max(scores)
        quality_bonus = 1.0
        if best_score > 0.9:
            quality_bonus = 1.2
        elif best_score > 0.8:
            quality_bonus = 1.1

        # 4. Combined final score
        confidence = min(0.95,
                        base_score * 0.7 +           # 70% weighted score
                        coherence_factor * 0.2 +     # 20% coherence
                        (best_score * 0.1) *         # 10% best result quality
                        quality_bonus
                        )

        logger.debug(
            f"Confidence computed: base={base_score:.3f}, coherence={coherence_factor:.3f}, "
            f"quality={quality_bonus:.3f}, final={confidence:.3f}"
        )

        return confidence

    else:
        # Fallback to the simple algorithm
        logger.warning(f"Unknown algorithm '{algorithm}', falling back to 'simple'")
        return _calculate_weighted_confidence(search_results, "simple")


def _filter_dynamic_sources(search_results: List[Any], config: Any, question: str = "") -> List[Any]:
    """
    Dynamically filter sources based on relevance with gap detection.

    Args:
        search_results: List of search results (sorted by descending score)
        config: Configuration with similarity_threshold, min_sources, max_sources
        question: Question for named entity detection

    Returns:
        Filtered list of relevant sources
    """
    if not search_results:
        return []

    scores = [r.similarity_score for r in search_results]
    best_score = scores[0]

    logger.debug(f"Dynamic filtering - Scores: {[f'{s:.3f}' for s in scores[:8]]}")

    # Dynamic filtering based on gap from the best score
    # Threshold = max(SIMILARITY_THRESHOLD, best_score x (1 - DYNAMIC_FILTER_PERCENTAGE))
    dynamic_threshold = best_score * (1 - config.dynamic_filter_percentage)
    final_threshold = max(config.similarity_threshold, dynamic_threshold)
    filtered_results = [r for r in search_results if r.similarity_score >= final_threshold]
    method = f"dynamic@{final_threshold:.3f}"

    logger.debug(f"Dynamic filtering: best={best_score:.3f}, gap={config.dynamic_filter_percentage:.2f}, "
                f"threshold={final_threshold:.3f}, {len(search_results)} → {len(filtered_results)} chunks")

    # 4. Enforce min/max constraints
    original_count = len(filtered_results)

    if len(filtered_results) < config.min_sources:
        filtered_results = search_results[:config.min_sources]
        method += f"→min({config.min_sources})"
    elif len(filtered_results) > config.max_sources:
        filtered_results = filtered_results[:config.max_sources]
        method += f"→max({config.max_sources})"

    # 5. Detailed filtering log
    logger.info(
        f"Dynamic sources: {len(search_results)} → {len(filtered_results)} sources "
        f"(method: {method})"
    )

    if len(filtered_results) != original_count:
        logger.debug(f"Constraint adjustment: {original_count} → {len(filtered_results)}")

    return filtered_results


async def _process_question_with_rag(
    question: str,
    context_limit: int,
    include_sources: bool,
    session_id: str,
    llm_service: MistralAPIService,
    vector_store: FaissVectorStore,
    document_repository: DocumentRepository,
    rag_debug: RagDebugService,
    budget_guard: Optional["BudgetGuard"] = None,
    usage_tracker: Optional["UsageTracker"] = None,
    reservation: Optional["BudgetReservation"] = None
) -> Dict[str, Any]:
    """
    Process question using RAG pipeline.

    Full RAG system implementation:
    1. Generate embeddings for the question
    2. Search vector store for relevant documents
    3. Build context from retrieved documents
    4. Generate response using LLM
    5. Format response with sources

    Args:
        question: User question
        context_limit: Maximum number of context documents
        include_sources: Whether to include source references
        session_id: Session identifier
        llm_service: LLM service for embeddings and generation
        vector_store: Vector store for similarity search
        budget_guard: Optional BudgetGuard used to finalize/release the
            caller's reservation once the real cost is known
        usage_tracker: Optional UsageTracker used to price and persist the
            embedding and generation usage rows
        reservation: The BudgetReservation captured by the caller before
            this pipeline started; settled (finalize or release) internally
            so the caller never has to reason about partial-failure cost

    Returns:
        dict: Response data
    """
    # Accumulates the real euro cost of every LLM call actually made, so the
    # reservation can be finalized with the true total instead of released
    # outright once at least one paid call has happened.
    total_cost_eur = 0.0
    llm_call_made = False
    try:
        # Step 1: Generate embeddings for the question
        logger.info(f"Generating embeddings for question: {question[:50]}...")
        start_embedding = datetime.utcnow()
        embedding_response = await llm_service.embed([question], session_id=session_id, rag_debug=rag_debug)
        embedding_time = (datetime.utcnow() - start_embedding).total_seconds() * 1000  # noqa: F841
        question_embedding = np.array(embedding_response.embeddings[0], dtype=np.float32)

        llm_call_made = True
        if usage_tracker is not None:
            # asyncio.to_thread: record() is a blocking SQLite write.
            total_cost_eur += await asyncio.to_thread(
                usage_tracker.record,
                "embedding",
                embedding_response.model,
                embedding_response.prompt_tokens,
                embedding_response.completion_tokens,
                estimated=False,
                session_id=session_id
            )

        # Step 1.5: Filename pre-inclusion (fuzzy matching)
        pre_included_chunks = []
        if settings.filename_pre_inclusion:
            logger.info(f"Checking for filename fuzzy matches...")  # noqa: F541
            matched_docs = _find_documents_by_fuzzy_match(
                question,
                document_repository,
                threshold=settings.filename_fuzzy_threshold
            )

            if matched_docs:
                # Prepare the similarities dictionary
                filename_similarities = {doc_id: score for doc_id, _, score in matched_docs}
                document_ids = [doc_id for doc_id, _, _ in matched_docs]

                # Pre-include all chunks from matched documents
                pre_included_chunks = await _pre_include_document_chunks(
                    document_ids=document_ids,
                    question_embedding=question_embedding,
                    vector_store=vector_store,
                    document_repository=document_repository,
                    boost_factor=settings.filename_boost,
                    filename_similarities=filename_similarities
                )

                logger.info(f"Pre-inclusion: {len(pre_included_chunks)} chunks from {len(matched_docs)} matched document(s)")

        # Step 2: Search vector store for relevant documents
        logger.info(f"Searching for relevant context in vector store...")  # noqa: F541
        start_search = datetime.utcnow()
        search_results = await asyncio.to_thread(vector_store.query,
            vector=question_embedding,
            top_k=settings.max_sources * 2,  # Retrieve more to filter afterwards
            filter_dict=None  # No filter for now
        )
        search_time = (datetime.utcnow() - start_search).total_seconds() * 1000

        # 2. Log vector search results for RAG debug
        rag_debug.log_vector_search(
            session_id=session_id,
            search_results=search_results,
            embedding_tokens=embedding_response.usage_tokens,
            search_time_ms=search_time
        )

        # Step 2.1: Merge pre-included chunks with vector search results
        if pre_included_chunks:
            # Create a set of pre-included chunk_ids to avoid duplicates
            pre_included_ids = {chunk.chunk_id for chunk in pre_included_chunks}

            # Filter vector results to remove duplicates
            unique_vector_results = [r for r in search_results if r.chunk_id not in pre_included_ids]

            # Merge: pre-included first, then vector results
            search_results = pre_included_chunks + unique_vector_results

            # Sort by descending score
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

            logger.info(f"Merge: {len(pre_included_chunks)} pre-included + {len(unique_vector_results)} vector = {len(search_results)} total")

        # Step 2.5: Apply dynamic source filtering
        if search_results:
            search_results = _filter_dynamic_sources(search_results, settings, question)

        # Step 3: Build context from retrieved documents
        context_parts = []
        sources = []

        if search_results:
            logger.info(f"Found {len(search_results)} relevant chunks")

            for result in search_results:
                context_parts.append(
                    f"[Source: {result.source}] {result.text}"
                )

                if include_sources:
                    # Retrieve the original document name
                    try:
                        document = document_repository.get_by_id(int(result.document_id))
                        filename = document.filename if document else str(result.source)
                    except Exception:
                        # Fallback if retrieval error
                        filename = str(result.source)

                    sources.append({
                        "document_id": int(result.document_id),
                        "filename": filename,
                        "chunk_text": result.text,
                        "similarity_score": float(round(result.similarity_score, 3)),
                        "chunk_index": int(result.chunk_index),
                        "total_chunks": int(result.total_chunks)
                    })

        # Step 4: Build prompt for LLM
        if context_parts:
            context_text = "\n\n".join(context_parts)
            system_prompt = MIMIR_SYSTEM_PROMPT
            full_prompt = system_prompt.format(context=context_text)
        else:
            # No context found
            logger.warning("No relevant context found in vector store")
            context_text = ""
            system_prompt = """Vous êtes Mimir, un assistant documentaire intelligent.
L'utilisateur vous pose une question mais aucun contexte pertinent n'a été trouvé dans la documentation.

Informez poliment l'utilisateur que vous ne trouvez pas d'information pertinente dans la documentation disponible pour répondre à sa question, et suggérez-lui de:
1. Reformuler sa question avec d'autres mots-clés
2. Contacter le support humain si nécessaire

Restez professionnel et utile."""
            full_prompt = system_prompt

        # 3. Log context building for RAG debug
        rag_debug.log_context_building(
            session_id=session_id,
            system_prompt=system_prompt,
            context_text=context_text,
            context_chunks=len(context_parts),
            filtered_sources=sources
        )

        # Step 5: Generate response using LLM
        logger.info("Generating response with LLM...")
        start_llm = datetime.utcnow()
        generation_response = await llm_service.generate(
            prompt=question,
            system_prompt=full_prompt,
            max_tokens=800,
            temperature=0.1,
            session_id=session_id,  # Pass session_id for LLM logging
            rag_debug=rag_debug  # Pass debug service for LLM logging
        )
        llm_time = (datetime.utcnow() - start_llm).total_seconds() * 1000  # noqa: F841

        if usage_tracker is not None:
            # asyncio.to_thread: record() is a blocking SQLite write.
            total_cost_eur += await asyncio.to_thread(
                usage_tracker.record,
                "chat",
                generation_response.model,
                generation_response.prompt_tokens,
                generation_response.completion_tokens,
                estimated=False,
                session_id=session_id
            )

        answer = generation_response.content


        # Calculate confidence score using the configured algorithm
        confidence_score = _calculate_weighted_confidence(
            search_results, settings.confidence_algorithm
        )

        logger.info(
            f"RAG response generated successfully - confidence: {confidence_score:.2f} "
            f"(algorithm: {settings.confidence_algorithm})"
        )

        return {
            "answer": answer,
            "sources": sources,
            "confidence_score": round(confidence_score, 2),
            "session_id": session_id,
            "cached": False,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"RAG pipeline failed: {str(e)}", exc_info=True)

        # Log error to RAG debug as well
        rag_debug.log_error(
            session_id=session_id,
            error_type=type(e).__name__,
            error_message=str(e),
            stage="rag_pipeline"
        )

        # Fallback response in case of error. The "error" marker is consumed
        # (popped) by the caller so it never reaches the client: it tells
        # chat() to SKIP caching -- otherwise a transient failure (Mistral
        # 500, network blip) would be served from cache for 30 minutes to
        # every identical question instead of being retried.
        return {
            "answer": "Je suis désolé, une erreur technique s'est produite lors du traitement de votre question. L'équipe technique a été notifiée. Veuillez réessayer dans quelques instants ou contacter le support si le problème persiste.",
            "sources": [],
            "confidence_score": 0.0,
            "session_id": session_id,
            "cached": False,
            "timestamp": datetime.utcnow(),
            "error": True
        }

    finally:
        # Settle the reservation exactly once, in a finally so it also runs
        # on asyncio.CancelledError (a BaseException in Python 3.11 that the
        # `except Exception` above does NOT catch -- e.g. server shutdown or
        # task cancellation during an awaited embed/generate call). Finalize
        # with whatever real cost was already incurred (e.g. embedding
        # succeeded but generation failed/was cancelled) or release outright
        # if no LLM call happened at all -- symmetric with the stream
        # variant's outer finally. asyncio.to_thread keeps the blocking
        # SQLite ledger write off the event loop.
        if budget_guard is not None and reservation is not None:
            if llm_call_made:
                await asyncio.to_thread(budget_guard.finalize, reservation, total_cost_eur)
            else:
                await asyncio.to_thread(budget_guard.release, reservation)


async def _process_question_with_rag_stream(
    question: str,
    context_limit: int,
    include_sources: bool,
    session_id: str,
    llm_service: MistralAPIService,
    vector_store: FaissVectorStore,
    document_repository: DocumentRepository,
    rag_debug: RagDebugService,
    budget_guard: Optional["BudgetGuard"] = None,
    usage_tracker: Optional["UsageTracker"] = None,
    reservation: Optional["BudgetReservation"] = None,
    chat_cache: Optional[Any] = None,
    corpus_version: Optional[str] = None
):
    """
    Process question using RAG pipeline with streaming.
    Yields SSE events as processing progresses.

    budget_guard/usage_tracker/reservation mirror _process_question_with_rag,
    but the reservation is settled in an OUTER finally block here (see below)
    because a mid-stream client disconnect throws GeneratorExit -- a
    BaseException, not caught by `except Exception` -- straight through this
    generator; only a finally at the outermost scope is guaranteed to run in
    every case (normal completion, error, or disconnect).
    """
    # Accumulates the real euro cost of every LLM call actually made.
    total_cost_eur = 0.0
    llm_call_made = False
    try:
        # Step 1: Generate embeddings
        logger.info(f"Generating embeddings for streaming question")  # noqa: F541
        start_embedding = datetime.utcnow()  # noqa: F841
        embedding_response = await llm_service.embed([question], session_id=session_id, rag_debug=rag_debug)
        question_embedding = np.array(embedding_response.embeddings[0], dtype=np.float32)

        llm_call_made = True
        if usage_tracker is not None:
            # asyncio.to_thread: record() is a blocking SQLite write.
            total_cost_eur += await asyncio.to_thread(
                usage_tracker.record,
                "embedding",
                embedding_response.model,
                embedding_response.prompt_tokens,
                embedding_response.completion_tokens,
                estimated=False,
                session_id=session_id
            )

        # Step 1.5: Filename pre-inclusion
        pre_included_chunks = []
        if settings.filename_pre_inclusion:
            matched_docs = _find_documents_by_fuzzy_match(
                question,
                document_repository,
                threshold=settings.filename_fuzzy_threshold
            )

            if matched_docs:
                filename_similarities = {doc_id: score for doc_id, _, score in matched_docs}
                document_ids = [doc_id for doc_id, _, _ in matched_docs]

                pre_included_chunks = await _pre_include_document_chunks(
                    document_ids=document_ids,
                    question_embedding=question_embedding,
                    vector_store=vector_store,
                    document_repository=document_repository,
                    boost_factor=settings.filename_boost,
                    filename_similarities=filename_similarities
                )

        # Step 2: Vector search
        start_search = datetime.utcnow()
        search_results = await asyncio.to_thread(vector_store.query,
            vector=question_embedding,
            top_k=settings.max_sources * 2,
            filter_dict=None
        )
        search_time = (datetime.utcnow() - start_search).total_seconds() * 1000

        rag_debug.log_vector_search(
            session_id=session_id,
            search_results=search_results,
            embedding_tokens=embedding_response.usage_tokens,
            search_time_ms=search_time
        )

        # Step 2.1: Merge pre-included chunks
        if pre_included_chunks:
            pre_included_ids = {chunk.chunk_id for chunk in pre_included_chunks}
            unique_vector_results = [r for r in search_results if r.chunk_id not in pre_included_ids]
            search_results = pre_included_chunks + unique_vector_results
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

        # Step 2.5: Apply filtering
        if search_results:
            search_results = _filter_dynamic_sources(search_results, settings, question)

        # Step 3: Build context
        context_parts = []
        sources = []

        if search_results:
            for result in search_results:
                context_parts.append(f"[Source: {result.source}] {result.text}")

                if include_sources:
                    try:
                        document = document_repository.get_by_id(int(result.document_id))
                        filename = document.filename if document else str(result.source)
                    except Exception:
                        filename = str(result.source)

                    sources.append({
                        "document_id": int(result.document_id),
                        "filename": filename,
                        "chunk_text": result.text,
                        "similarity_score": float(round(result.similarity_score, 3)),
                        "chunk_index": int(result.chunk_index),
                        "total_chunks": int(result.total_chunks)
                    })

        # Step 4: Build prompt
        if context_parts:
            context_text = "\n\n".join(context_parts)
            system_prompt = MIMIR_SYSTEM_PROMPT
            full_prompt = system_prompt.format(context=context_text)
        else:
            logger.warning("No relevant context found")
            context_text = ""
            system_prompt = """Vous êtes Mimir, un assistant documentaire intelligent.
L'utilisateur vous pose une question mais aucun contexte pertinent n'a été trouvé dans la documentation."""
            full_prompt = system_prompt

        rag_debug.log_context_building(
            session_id=session_id,
            system_prompt=system_prompt,
            context_text=context_text,
            context_chunks=len(context_parts),
            filtered_sources=sources
        )

        # Step 5: Stream LLM generation
        logger.info("Starting streaming LLM generation...")
        full_answer = ""
        usage_out: Dict[str, Any] = {}
        chat_usage_recorded = False

        try:
            async for chunk in llm_service.generate_stream(
                prompt=question,
                system_prompt=full_prompt,
                max_tokens=800,
                temperature=0.1,
                session_id=session_id,
                rag_debug=rag_debug,
                usage_out=usage_out
            ):
                full_answer += chunk
                yield {"type": "chunk", "content": chunk}

            # Stream completed and the final SSE chunk carried real usage.
            if usage_tracker is not None and usage_out:
                # asyncio.to_thread: record() is a blocking SQLite write.
                total_cost_eur += await asyncio.to_thread(
                    usage_tracker.record,
                    "chat",
                    llm_service.model_name,
                    usage_out.get("prompt_tokens", 0),
                    usage_out.get("completion_tokens", 0),
                    estimated=False,
                    session_id=session_id
                )
                chat_usage_recorded = True
        finally:
            # Guarantee exactly one chat usage row per request (T-03-12): if
            # the async-for loop ended -- normal completion without a final
            # usage chunk, an exception, or a mid-stream client disconnect
            # (GeneratorExit) -- without recording real usage above, estimate
            # tokens from the text lengths instead. The prompt side MUST be
            # estimated too: Mistral bills the full prompt (system prompt +
            # entire document context) even for an interrupted stream, and
            # in this RAG pipeline the prompt is usually the dominant share
            # of billed tokens -- recording prompt_tokens=0 would make the
            # ledger drift below the real Mistral spend on every disconnect.
            # asyncio.to_thread: awaiting (no yield) in an async generator's
            # finally is legal during aclose(); keeps the blocking SQLite
            # write off the event loop.
            if usage_tracker is not None and not chat_usage_recorded:
                estimated_prompt_tokens = max(1, (len(full_prompt) + len(question)) // 4)
                estimated_completion_tokens = max(1, len(full_answer) // 4)
                total_cost_eur += await asyncio.to_thread(
                    usage_tracker.record,
                    "chat",
                    llm_service.model_name,
                    estimated_prompt_tokens,
                    estimated_completion_tokens,
                    estimated=True,
                    session_id=session_id
                )
                chat_usage_recorded = True

        # Calculate confidence
        confidence_score = _calculate_weighted_confidence(search_results, settings.confidence_algorithm)

        # Send completion event - convert numpy types to Python native
        yield {
            "type": "done",
            "sources": sources,
            "confidence_score": float(round(confidence_score, 2)),
            "cached": False
        }

        logger.info(f"Streaming RAG completed - confidence: {confidence_score:.2f}")

        # Anti-partial cache write (COST-03, T-4-05-03 / WR-05): store the
        # streamed answer ONLY here, on the fully-successful path AFTER the
        # done event was yielded. This is deliberately NOT in the `except`
        # branch (an error response is never cached) and NOT in a `finally`
        # (which also runs on GeneratorExit / mid-stream client disconnect),
        # so no partial or error entry can ever be stored. set_stream_response
        # performs no await/yield, so a GeneratorExit cannot interrupt between
        # the done yield resuming here and the write completing.
        if chat_cache is not None and corpus_version is not None:
            chat_cache.set_stream_response(
                question,
                corpus_version,
                {
                    "answer": full_answer,
                    "sources": sources,
                    "confidence_score": float(round(confidence_score, 2)),
                }
            )

    except Exception as e:
        logger.error(f"Streaming RAG pipeline failed: {str(e)}", exc_info=True)
        rag_debug.log_error(
            session_id=session_id,
            error_type=type(e).__name__,
            error_message=str(e),
            stage="streaming_rag_pipeline"
        )
        # Generic client-facing message; details stay in logs/rag_debug only
        yield {"type": "error", "message": "Une erreur interne est survenue."}

    finally:
        # Settle the reservation exactly once, regardless of normal
        # completion, an exception caught above, or a mid-stream client
        # disconnect (GeneratorExit propagates straight through the except
        # clause -- which only catches Exception -- but always runs this
        # finally before the generator closes). asyncio.to_thread keeps the
        # blocking SQLite ledger write off the event loop; awaiting (no
        # yield) in a finally is legal during aclose().
        if budget_guard is not None and reservation is not None:
            if llm_call_made:
                await asyncio.to_thread(budget_guard.finalize, reservation, total_cost_eur)
            else:
                await asyncio.to_thread(budget_guard.release, reservation)


class RagService:
    """
    Framework-agnostic RAG pipeline service.

    Wraps the module-level pipeline functions above so the full pipeline can
    be constructed once via dependency injection (see
    backend/src/api/dependencies.py::get_rag_service) and reused outside an
    HTTP request context -- notably by the Phase 6 RAGAS evaluation harness,
    which will call answer()/answer_stream() directly.

    document_repository is intentionally NOT stored as an instance
    attribute: it wraps a request-scoped SQLAlchemy session (FastAPI
    Depends(get_document_repository)), so it must be passed as a per-call
    argument to answer()/answer_stream() to avoid leaking a session across
    requests.
    """

    def __init__(
        self,
        llm_service: MistralAPIService,
        vector_store: FaissVectorStore,
        rag_debug: RagDebugService,
        budget_guard: Optional[BudgetGuard] = None,
        usage_tracker: Optional[UsageTracker] = None,
        chat_cache: Optional[Any] = None,
    ):
        self.llm_service = llm_service
        self.vector_store = vector_store
        self.rag_debug = rag_debug
        self.budget_guard = budget_guard
        self.usage_tracker = usage_tracker
        self.chat_cache = chat_cache

    async def answer(
        self,
        question: str,
        context_limit: int,
        include_sources: bool,
        session_id: str,
        document_repository: DocumentRepository,
        reservation: Optional[BudgetReservation] = None,
    ) -> Dict[str, Any]:
        """
        Run the non-streaming RAG pipeline for a single question.

        Settles `reservation` (finalize or release) internally via its own
        inner `finally`, exactly as the moved `_process_question_with_rag`
        did in chat.py -- callers never need to settle it themselves once
        this method has been entered.
        """
        return await _process_question_with_rag(
            question=question,
            context_limit=context_limit,
            include_sources=include_sources,
            session_id=session_id,
            llm_service=self.llm_service,
            vector_store=self.vector_store,
            document_repository=document_repository,
            rag_debug=self.rag_debug,
            budget_guard=self.budget_guard,
            usage_tracker=self.usage_tracker,
            reservation=reservation,
        )

    async def answer_stream(
        self,
        question: str,
        context_limit: int,
        include_sources: bool,
        session_id: str,
        document_repository: DocumentRepository,
        reservation: Optional[BudgetReservation] = None,
        corpus_version: Optional[str] = None,
    ):
        """
        Run the streaming RAG pipeline for a single question, yielding the
        same SSE event dicts as `_process_question_with_rag_stream`.

        Settles `reservation` in an outer `finally` internally, covering
        normal completion, an exception, and a mid-stream GeneratorExit
        (client disconnect) -- exactly as the moved function did.

        When `corpus_version` is supplied and this service was constructed
        with a `chat_cache`, the fully-successful streamed answer is written
        to the corpus-aware SSE cache after the done event (COST-03); the
        write is on the success path only, never on error or disconnect.
        """
        async for event in _process_question_with_rag_stream(
            question=question,
            context_limit=context_limit,
            include_sources=include_sources,
            session_id=session_id,
            llm_service=self.llm_service,
            vector_store=self.vector_store,
            document_repository=document_repository,
            rag_debug=self.rag_debug,
            budget_guard=self.budget_guard,
            usage_tracker=self.usage_tracker,
            reservation=reservation,
            chat_cache=self.chat_cache,
            corpus_version=corpus_version,
        ):
            yield event
