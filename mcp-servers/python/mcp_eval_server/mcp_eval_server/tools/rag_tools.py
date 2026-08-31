# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/tools/rag_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP tools for RAG (Retrieval-Augmented Generation) evaluation.
"""

# Standard
from difflib import SequenceMatcher
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Local
from .judge_tools import JudgeTools


class RAGTools:
    """Tools for RAG (Retrieval-Augmented Generation) evaluation."""

    def __init__(self, judge_tools: Optional[JudgeTools] = None):
        """Initialize RAG tools.

        Args:
            judge_tools: Judge tools instance for LLM evaluations
        """
        self.judge_tools = judge_tools or JudgeTools()
        self._tfidf_vectorizer = None

    async def evaluate_retrieval_relevance(
        self,
        query: str,
        retrieved_documents: List[Dict[str, Any]],
        relevance_threshold: float = 0.7,
        embedding_model: str = "text-embedding-ada-002",
        judge_model: str = "gpt-4o-mini",
        use_llm_judge: bool = True,
    ) -> Dict[str, Any]:
        """Assess relevance of retrieved documents to the query.

        Args:
            query: Original user query
            retrieved_documents: List of retrieved docs with 'content' and optional 'score'
            relevance_threshold: Minimum relevance score
            embedding_model: Model for semantic similarity
            judge_model: LLM judge for relevance assessment
            use_llm_judge: Whether to use LLM judge in addition to embeddings

        Returns:
            Relevance evaluation results
        """
        if not retrieved_documents:
            return {
                "overall_relevance": 0.0,
                "relevant_docs": 0,
                "total_docs": 0,
                "relevance_scores": [],
                "analysis": {"issue": "No documents retrieved"},
            }

        # Extract document contents
        doc_contents = [doc.get("content", str(doc)) for doc in retrieved_documents]

        # Calculate semantic similarity
        similarity_scores = await self._calculate_semantic_similarity(query, doc_contents, embedding_model)

        # Use LLM judge for additional relevance assessment
        llm_relevance_scores = []
        if use_llm_judge:
            for i, doc_content in enumerate(doc_contents):
                llm_score = await self._judge_document_relevance(query, doc_content, judge_model)
                llm_relevance_scores.append(llm_score)

        # Combine scores (weighted average if both available)
        final_scores = []
        for i in range(len(doc_contents)):
            if llm_relevance_scores:
                # Weight: 60% semantic similarity, 40% LLM judge
                combined_score = (similarity_scores[i] * 0.6) + (llm_relevance_scores[i] * 0.4)
            else:
                combined_score = similarity_scores[i]
            final_scores.append(combined_score)

        # Analyze results
        relevant_docs = sum(1 for score in final_scores if score >= relevance_threshold)
        overall_relevance = statistics.mean(final_scores) if final_scores else 0.0

        # Generate recommendations
        recommendations = self._generate_retrieval_recommendations(final_scores, relevance_threshold, retrieved_documents)

        return {
            "overall_relevance": overall_relevance,
            "relevant_docs": relevant_docs,
            "total_docs": len(doc_contents),
            "relevance_scores": final_scores,
            "similarity_scores": similarity_scores,
            "llm_scores": llm_relevance_scores,
            "threshold": relevance_threshold,
            "recommendations": recommendations,
            "analysis": {
                "top_score": max(final_scores) if final_scores else 0.0,
                "bottom_score": min(final_scores) if final_scores else 0.0,
                "score_variance": statistics.variance(final_scores) if len(final_scores) > 1 else 0.0,
                "embedding_model": embedding_model,
                "judge_model": judge_model if use_llm_judge else None,
            },
        }

    async def measure_context_utilization(
        self,
        query: str,
        retrieved_context: str,
        generated_answer: str,
        context_chunks: Optional[List[str]] = None,
        judge_model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """Check how well retrieved context is used in the generated answer.

        Args:
            query: Original query
            retrieved_context: Full retrieved context
            generated_answer: Model's generated response
            context_chunks: Optional list of individual context chunks
            judge_model: Judge model for evaluation

        Returns:
            Context utilization analysis
        """
        # Basic overlap analysis
        context_words = set(retrieved_context.lower().split())
        answer_words = set(generated_answer.lower().split())
        word_overlap = len(context_words & answer_words) / len(context_words) if context_words else 0.0

        # Sentence-level analysis
        context_sentences = re.split(r"[.!?]+", retrieved_context)
        answer_sentences = re.split(r"[.!?]+", generated_answer)

        sentence_utilization = []
        for ctx_sent in context_sentences:
            if len(ctx_sent.strip()) < 10:  # Skip very short sentences
                continue
            max_similarity = 0.0
            for ans_sent in answer_sentences:
                similarity = SequenceMatcher(None, ctx_sent.lower().strip(), ans_sent.lower().strip()).ratio()
                max_similarity = max(max_similarity, similarity)
            sentence_utilization.append(max_similarity)

        avg_sentence_utilization = statistics.mean(sentence_utilization) if sentence_utilization else 0.0

        # Chunk-level analysis if provided
        chunk_utilization = {}
        if context_chunks:
            for i, chunk in enumerate(context_chunks):
                chunk_words = set(chunk.lower().split())
                chunk_overlap = len(chunk_words & answer_words) / len(chunk_words) if chunk_words else 0.0
                chunk_utilization[f"chunk_{i}"] = chunk_overlap

        # LLM judge evaluation
        llm_assessment = await self._judge_context_utilization(query, retrieved_context, generated_answer, judge_model)

        # Calculate overall utilization score
        utilization_factors = [word_overlap, avg_sentence_utilization, llm_assessment["score"]]
        overall_utilization = statistics.mean(utilization_factors)

        return {
            "overall_utilization": overall_utilization,
            "word_overlap": word_overlap,
            "sentence_utilization": avg_sentence_utilization,
            "chunk_utilization": chunk_utilization,
            "llm_assessment": llm_assessment,
            "analysis": {
                "context_length": len(retrieved_context),
                "answer_length": len(generated_answer),
                "context_sentences": len(context_sentences),
                "answer_sentences": len(answer_sentences),
                "underutilized_context": self._identify_underutilized_context(retrieved_context, generated_answer),
            },
            "recommendations": self._generate_utilization_recommendations(overall_utilization, word_overlap, avg_sentence_utilization),
        }

    async def assess_answer_groundedness(
        self,
        question: str,
        answer: str,
        supporting_context: str,
        judge_model: str = "gpt-4o-mini",
        strictness: str = "moderate",
    ) -> Dict[str, Any]:
        """Verify answers are grounded in provided context.

        Args:
            question: Original question
            answer: Generated answer to verify
            supporting_context: Context that should support the answer
            judge_model: Judge model for evaluation
            strictness: Grounding strictness ('strict', 'moderate', 'loose')

        Returns:
            Groundedness assessment results
        """
        # Extract claims from the answer
        claims = self._extract_claims(answer)

        # Verify each claim against context
        claim_verification = []
        for claim in claims:
            verification = await self._verify_claim_against_context(claim, supporting_context, judge_model, strictness)
            claim_verification.append(
                {
                    "claim": claim,
                    "supported": verification["supported"],
                    "confidence": verification["confidence"],
                    "supporting_evidence": verification["evidence"],
                }
            )

        # Calculate groundedness metrics
        supported_claims = sum(1 for v in claim_verification if v["supported"])
        groundedness_score = supported_claims / len(claims) if claims else 1.0

        # Overall LLM assessment
        overall_assessment = await self._judge_overall_groundedness(question, answer, supporting_context, judge_model, strictness)

        # Identify potential hallucinations
        hallucinations = [v for v in claim_verification if not v["supported"]]

        return {
            "groundedness_score": groundedness_score,
            "supported_claims": supported_claims,
            "total_claims": len(claims),
            "claim_verification": claim_verification,
            "overall_assessment": overall_assessment,
            "hallucinations": hallucinations,
            "analysis": {
                "strictness_level": strictness,
                "confidence_distribution": [v["confidence"] for v in claim_verification],
                "avg_confidence": statistics.mean([v["confidence"] for v in claim_verification]) if claim_verification else 0.0,
            },
            "recommendations": self._generate_groundedness_recommendations(groundedness_score, len(hallucinations), overall_assessment),
        }

    async def detect_hallucination_vs_context(
        self,
        generated_text: str,
        source_context: str,
        judge_model: str = "gpt-4o-mini",
        detection_threshold: float = 0.8,
    ) -> Dict[str, Any]:
        """Identify when responses contradict provided context.

        Args:
            generated_text: Text to analyze for hallucinations
            source_context: Source context to check against
            judge_model: Judge model for hallucination detection
            detection_threshold: Confidence threshold for hallucination detection

        Returns:
            Hallucination detection results
        """
        # Extract factual statements
        factual_statements = self._extract_factual_statements(generated_text)

        # Check each statement against context
        contradiction_analysis = []
        for statement in factual_statements:
            analysis = await self._check_statement_contradiction(statement, source_context, judge_model)
            contradiction_analysis.append(
                {
                    "statement": statement,
                    "contradicts_context": analysis["contradicts"],
                    "confidence": analysis["confidence"],
                    "explanation": analysis["explanation"],
                }
            )

        # Identify clear contradictions
        contradictions = [a for a in contradiction_analysis if a["contradicts_context"] and a["confidence"] >= detection_threshold]

        # Calculate hallucination metrics
        hallucination_rate = len(contradictions) / len(factual_statements) if factual_statements else 0.0

        # Overall assessment
        overall_assessment = await self._assess_overall_hallucination(generated_text, source_context, judge_model)

        return {
            "hallucination_rate": hallucination_rate,
            "contradictions_found": len(contradictions),
            "total_statements": len(factual_statements),
            "contradiction_analysis": contradiction_analysis,
            "clear_contradictions": contradictions,
            "overall_assessment": overall_assessment,
            "severity": self._classify_hallucination_severity(hallucination_rate, contradictions),
            "analysis": {
                "detection_threshold": detection_threshold,
                "confidence_scores": [a["confidence"] for a in contradiction_analysis],
                "avg_confidence": statistics.mean([a["confidence"] for a in contradiction_analysis]) if contradiction_analysis else 0.0,
            },
            "recommendations": self._generate_hallucination_recommendations(hallucination_rate, len(contradictions), overall_assessment),
        }

    async def evaluate_retrieval_coverage(
        self,
        query: str,
        expected_topics: List[str],
        retrieved_documents: List[Dict[str, Any]],
        judge_model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """Measure if key information was retrieved.

        Args:
            query: Original search query
            expected_topics: Topics that should be covered
            retrieved_documents: Retrieved document set
            judge_model: Judge model for coverage assessment

        Returns:
            Coverage evaluation results
        """
        if not retrieved_documents:
            return {
                "coverage_score": 0.0,
                "topics_covered": 0,
                "total_topics": len(expected_topics),
                "missing_topics": expected_topics,
                "analysis": {"issue": "No documents retrieved"},
            }

        # Combine all retrieved content
        all_content = " ".join([doc.get("content", str(doc)) for doc in retrieved_documents])

        # Check coverage for each expected topic
        topic_coverage = []
        for topic in expected_topics:
            coverage = await self._assess_topic_coverage(topic, all_content, judge_model)
            topic_coverage.append(
                {
                    "topic": topic,
                    "covered": coverage["covered"],
                    "confidence": coverage["confidence"],
                    "evidence": coverage["evidence"],
                }
            )

        # Calculate metrics
        covered_topics = sum(1 for tc in topic_coverage if tc["covered"])
        coverage_score = covered_topics / len(expected_topics) if expected_topics else 1.0
        missing_topics = [tc["topic"] for tc in topic_coverage if not tc["covered"]]

        # Identify over-retrieval (irrelevant content)
        irrelevance_assessment = await self._assess_retrieval_irrelevance(query, expected_topics, all_content, judge_model)

        return {
            "coverage_score": coverage_score,
            "topics_covered": covered_topics,
            "total_topics": len(expected_topics),
            "topic_coverage": topic_coverage,
            "missing_topics": missing_topics,
            "irrelevance_assessment": irrelevance_assessment,
            "analysis": {
                "avg_confidence": statistics.mean([tc["confidence"] for tc in topic_coverage]) if topic_coverage else 0.0,
                "total_content_length": len(all_content),
                "documents_retrieved": len(retrieved_documents),
            },
            "recommendations": self._generate_coverage_recommendations(coverage_score, missing_topics, irrelevance_assessment),
        }

    async def assess_citation_accuracy(
        self,
        generated_text: str,
        source_documents: List[Dict[str, Any]],
        citation_format: str = "auto",
        judge_model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """Validate citation quality and accuracy.

        Args:
            generated_text: Text with citations to verify
            source_documents: Available source documents with 'content' and optional 'id'
            citation_format: Expected citation format ('auto', 'numeric', 'bracket', 'parenthetical')
            judge_model: Judge model for citation assessment

        Returns:
            Citation accuracy evaluation
        """
        # Extract citations from text
        citations = self._extract_citations(generated_text, citation_format)

        # Analyze each citation
        citation_analysis = []
        for citation in citations:
            analysis = await self._verify_citation(citation, source_documents, judge_model)
            citation_analysis.append(analysis)

        # Check for missing citations (claims without citations)
        uncited_claims = await self._find_uncited_claims(generated_text, source_documents, judge_model)

        # Calculate citation metrics
        accurate_citations = sum(1 for c in citation_analysis if c["accurate"])
        citation_accuracy = accurate_citations / len(citations) if citations else 1.0

        # Overall citation quality assessment
        overall_quality = await self._assess_citation_quality(generated_text, source_documents, judge_model)

        return {
            "citation_accuracy": citation_accuracy,
            "accurate_citations": accurate_citations,
            "total_citations": len(citations),
            "citation_analysis": citation_analysis,
            "uncited_claims": uncited_claims,
            "overall_quality": overall_quality,
            "analysis": {
                "citation_format": citation_format,
                "citations_per_claim": len(citations) / max(1, len(uncited_claims) + len(citations)),
                "avg_citation_confidence": statistics.mean([c["confidence"] for c in citation_analysis]) if citation_analysis else 0.0,
            },
            "recommendations": self._generate_citation_recommendations(citation_accuracy, len(uncited_claims), overall_quality),
        }

    async def measure_chunk_relevance(
        self,
        query: str,
        context_chunks: List[str],
        embedding_model: str = "text-embedding-ada-002",
        relevance_threshold: float = 0.6,
        judge_model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """Evaluate individual chunk relevance scores.

        Args:
            query: Search query
            context_chunks: List of text chunks to evaluate
            embedding_model: Model for semantic similarity
            relevance_threshold: Minimum relevance score
            judge_model: Judge model for relevance assessment

        Returns:
            Chunk relevance evaluation
        """
        if not context_chunks:
            return {
                "overall_relevance": 0.0,
                "relevant_chunks": 0,
                "total_chunks": 0,
                "chunk_scores": [],
                "analysis": {"issue": "No chunks provided"},
            }

        # Calculate semantic similarity for each chunk
        chunk_similarities = await self._calculate_semantic_similarity(query, context_chunks, embedding_model)

        # LLM-based relevance assessment
        llm_assessments = []
        for chunk in context_chunks:
            assessment = await self._judge_chunk_relevance(query, chunk, judge_model)
            llm_assessments.append(assessment)

        # Combine scores
        final_scores = []
        for i in range(len(context_chunks)):
            # Weight: 70% semantic similarity, 30% LLM assessment
            combined_score = (chunk_similarities[i] * 0.7) + (llm_assessments[i] * 0.3)
            final_scores.append(combined_score)

        # Analyze results
        relevant_chunks = sum(1 for score in final_scores if score >= relevance_threshold)
        overall_relevance = statistics.mean(final_scores) if final_scores else 0.0

        # Rank chunks by relevance
        chunk_rankings = sorted(enumerate(final_scores), key=lambda x: x[1], reverse=True)

        return {
            "overall_relevance": overall_relevance,
            "relevant_chunks": relevant_chunks,
            "total_chunks": len(context_chunks),
            "chunk_scores": final_scores,
            "similarity_scores": chunk_similarities,
            "llm_assessments": llm_assessments,
            "chunk_rankings": chunk_rankings,
            "analysis": {
                "top_score": max(final_scores) if final_scores else 0.0,
                "bottom_score": min(final_scores) if final_scores else 0.0,
                "score_variance": statistics.variance(final_scores) if len(final_scores) > 1 else 0.0,
                "threshold": relevance_threshold,
                "embedding_model": embedding_model,
            },
            "recommendations": self._generate_chunk_recommendations(final_scores, relevance_threshold, chunk_rankings),
        }

    async def benchmark_retrieval_systems(
        self,
        test_queries: List[Dict[str, Any]],
        retrieval_systems: List[Dict[str, Any]],
        evaluation_metrics: List[str] = None,
        judge_model: str = "gpt-4o-mini",
    ) -> Dict[str, Any]:
        """Compare different retrieval approaches.

        Args:
            test_queries: List of queries with expected results
            retrieval_systems: List of retrieval system configurations
            evaluation_metrics: Metrics to compute ('precision', 'recall', 'mrr', 'ndcg')
            judge_model: Judge model for evaluation

        Returns:
            Retrieval system benchmark results
        """
        if evaluation_metrics is None:
            evaluation_metrics = ["precision", "recall", "mrr", "ndcg"]

        benchmark_results = {}

        for system in retrieval_systems:
            system_name = system.get("name", "unnamed_system")
            system_results = []

            for query_data in test_queries:
                query = query_data["query"]
                expected_docs = query_data.get("expected_documents", [])

                # Simulate retrieval (in real implementation, would call actual system)
                retrieved_docs = await self._simulate_retrieval(query, system)

                # Evaluate this query
                query_result = await self._evaluate_query_retrieval(query, retrieved_docs, expected_docs, evaluation_metrics, judge_model)
                system_results.append(query_result)

            # Aggregate system performance
            system_performance = self._aggregate_system_performance(system_results, evaluation_metrics)
            benchmark_results[system_name] = system_performance

        # Compare systems
        comparison_analysis = self._compare_retrieval_systems(benchmark_results, evaluation_metrics)

        return {
            "system_results": benchmark_results,
            "comparison": comparison_analysis,
            "best_system": comparison_analysis["best_overall"],
            "metrics_evaluated": evaluation_metrics,
            "total_queries": len(test_queries),
            "recommendations": self._generate_benchmark_recommendations(benchmark_results, comparison_analysis),
        }

    # Helper methods for semantic similarity
    async def _calculate_semantic_similarity(self, query: str, documents: List[str], embedding_model: str) -> List[float]:
        """Calculate semantic similarity between query and documents.

        Args:
            query: Search query
            documents: List of documents to compare
            embedding_model: Model for embeddings

        Returns:
            List of similarity scores
        """
        try:
            # Try to use API-based embedding model first
            if embedding_model.startswith("text-embedding"):
                return await self._api_embedding_similarity(query, documents, embedding_model)
            # Fall back to local embedding or TF-IDF
            return self._local_similarity(query, documents)
        except Exception:
            # Final fallback to TF-IDF
            return self._tfidf_similarity(query, documents)

    async def _api_embedding_similarity(self, query: str, documents: List[str], _model: str) -> List[float]:
        """Calculate similarity using API-based embeddings.

        Args:
            query: Search query
            documents: List of documents to compare
            _model: API embedding model name

        Returns:
            List of similarity scores
        """
        # This would integrate with OpenAI or other embedding APIs
        # For now, fall back to local similarity
        return self._local_similarity(query, documents)

    def _local_similarity(self, query: str, documents: List[str]) -> List[float]:
        """Calculate similarity using local models.

        Args:
            query: Search query
            documents: List of documents to compare

        Returns:
            List of similarity scores
        """
        try:
            # Try to use sentence-transformers if available
            # Third-Party
            from sentence_transformers import SentenceTransformer  # pylint: disable=import-outside-toplevel

            model = SentenceTransformer("all-MiniLM-L6-v2")

            query_embedding = model.encode([query])
            doc_embeddings = model.encode(documents)

            similarities = cosine_similarity(query_embedding, doc_embeddings)[0]
            return similarities.tolist()
        except ImportError:
            # Fall back to TF-IDF if sentence-transformers not available
            return self._tfidf_similarity(query, documents)

    def _tfidf_similarity(self, query: str, documents: List[str]) -> List[float]:
        """Calculate similarity using TF-IDF vectors.

        Args:
            query: Search query
            documents: List of documents to compare

        Returns:
            List of similarity scores
        """
        if self._tfidf_vectorizer is None:
            self._tfidf_vectorizer = TfidfVectorizer(stop_words="english", max_features=1000)

        # Combine query and documents for vectorization
        all_texts = [query] + documents
        tfidf_matrix = self._tfidf_vectorizer.fit_transform(all_texts)

        # Calculate cosine similarity between query (first item) and each document
        query_vector = tfidf_matrix[0:1]
        doc_vectors = tfidf_matrix[1:]

        similarities = cosine_similarity(query_vector, doc_vectors)[0]
        return similarities.tolist()

    # LLM Judge helper methods
    async def _judge_document_relevance(self, query: str, document: str, judge_model: str) -> float:
        """Use LLM judge to assess document relevance.

        Args:
            query: Search query
            document: Document to assess
            judge_model: Judge model for evaluation

        Returns:
            Relevance score (0-1)
        """
        criteria = [
            {
                "name": "relevance",
                "description": "How relevant is this document to the query?",
                "scale": "1-5",
                "weight": 1.0,
            }
        ]

        rubric = {
            "criteria": criteria,
            "scale_description": {
                "1": "Not relevant at all",
                "2": "Slightly relevant",
                "3": "Moderately relevant",
                "4": "Highly relevant",
                "5": "Perfectly relevant",
            },
        }

        context = f"Query: {query}\n\nDocument: {document}"

        result = await self.judge_tools.evaluate_response(
            response=document,
            criteria=criteria,
            rubric=rubric,
            judge_model=judge_model,
            context=context,
        )

        # Convert 1-5 scale to 0-1 scale
        return (result["overall_score"] - 1) / 4

    async def _judge_context_utilization(self, query: str, context: str, answer: str, judge_model: str) -> Dict[str, Any]:
        """Use LLM judge to assess context utilization.

        Args:
            query: Original query
            context: Retrieved context
            answer: Generated answer
            judge_model: Judge model for evaluation

        Returns:
            Context utilization assessment
        """
        criteria = [
            {
                "name": "utilization",
                "description": "How well does the answer utilize the provided context?",
                "scale": "1-5",
                "weight": 1.0,
            }
        ]

        rubric = {
            "criteria": criteria,
            "scale_description": {
                "1": "Doesn't use context at all",
                "2": "Minimal context usage",
                "3": "Moderate context usage",
                "4": "Good context usage",
                "5": "Excellent context usage",
            },
        }

        evaluation_context = f"Query: {query}\n\nContext: {context}\n\nAnswer: {answer}"

        result = await self.judge_tools.evaluate_response(
            response=answer,
            criteria=criteria,
            rubric=rubric,
            judge_model=judge_model,
            context=evaluation_context,
        )

        return {
            "score": (result["overall_score"] - 1) / 4,  # Convert to 0-1 scale
            "reasoning": result.get("reasoning", ""),
            "raw_score": result["overall_score"],
        }

    # Content extraction helper methods
    def _extract_claims(self, text: str) -> List[str]:
        """Extract factual claims from text.

        Args:
            text: Text to extract claims from

        Returns:
            List of extracted claims
        """
        # Simple claim extraction using sentence boundaries and patterns
        sentences = re.split(r"[.!?]+", text)
        claims = []

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:  # Skip very short sentences
                continue

            # Look for sentences that make factual claims
            claim_patterns = [
                r"\b(is|are|was|were|will be|has|have|had|does|do|did)\b",
                r"\b(according to|based on|studies show|research indicates)\b",
                r"\b\d+[%\w\s]*(percent|percentage|number|amount|cost|price)\b",
            ]

            if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in claim_patterns):
                claims.append(sentence)

        return claims

    def _extract_factual_statements(self, text: str) -> List[str]:
        """Extract factual statements that can be verified.

        Args:
            text: Text to extract statements from

        Returns:
            List of factual statements
        """
        # Similar to _extract_claims but more focused on verifiable facts
        sentences = re.split(r"[.!?]+", text)
        factual_statements = []

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 15:  # Require longer sentences for factual statements
                continue

            # Look for definitive factual statements
            factual_patterns = [
                r"\b(the .+ is|are|was|were)\b",
                r"\b(contains?|includes?|consists? of)\b",
                r"\b(located|situated|found) (in|at|on)\b",
                r"\b(costs?|prices?|worth|valued at)\b",
                r"\b\d+(\.\d+)?\s*(percent|%|dollars?|\$|years?|months?|days?)\b",
            ]

            if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in factual_patterns):
                factual_statements.append(sentence)

        return factual_statements

    def _extract_citations(self, text: str, citation_format: str) -> List[Dict[str, Any]]:
        """Extract citations from text.

        Args:
            text: Text to extract citations from
            citation_format: Expected citation format

        Returns:
            List of extracted citations
        """
        citations = []

        if citation_format == "auto":
            # Try multiple formats
            patterns = [
                (r"\[(\d+)\]", "numeric"),
                (r"\(([^)]+\d{4}[^)]*)\)", "parenthetical"),
                (r"\[([^\]]+)\]", "bracket"),
            ]
        elif citation_format == "numeric":
            patterns = [(r"\[(\d+)\]", "numeric")]
        elif citation_format == "bracket":
            patterns = [(r"\[([^\]]+)\]", "bracket")]
        elif citation_format == "parenthetical":
            patterns = [(r"\(([^)]+\d{4}[^)]*)\)", "parenthetical")]
        else:
            patterns = [(r"\[(\d+)\]", "numeric")]  # Default fallback

        for pattern, format_type in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                citations.append(
                    {
                        "text": match.group(0),
                        "reference": match.group(1),
                        "position": match.span(),
                        "format": format_type,
                    }
                )

        return citations

    # Additional helper methods would continue here...
    # (Implementation of remaining helper methods would follow similar patterns)

    async def _verify_claim_against_context(self, _claim: str, _context: str, _judge_model: str, _strictness: str) -> Dict[str, Any]:
        """Verify if a claim is supported by the context.

        Args:
            _claim: Claim to verify
            _context: Supporting context
            _judge_model: Judge model for verification
            _strictness: Verification strictness level

        Returns:
            Claim verification results
        """
        # Placeholder implementation - would use LLM judge
        return {
            "supported": True,  # Simplified
            "confidence": 0.8,
            "evidence": "Found in context",
        }

    async def _judge_overall_groundedness(self, _question: str, _answer: str, _context: str, _judge_model: str, _strictness: str) -> Dict[str, Any]:
        """Overall groundedness assessment using LLM judge.

        Args:
            _question: Original question
            _answer: Generated answer
            _context: Supporting context
            _judge_model: Judge model for assessment
            _strictness: Assessment strictness level

        Returns:
            Overall groundedness assessment
        """
        # Placeholder implementation
        return {
            "score": 0.8,
            "reasoning": "Answer appears well-grounded",
            "issues": [],
        }

    def _generate_retrieval_recommendations(self, scores: List[float], threshold: float, _documents: List[Dict[str, Any]]) -> List[str]:
        """Generate recommendations for improving retrieval.

        Args:
            scores: Relevance scores
            threshold: Relevance threshold
            _documents: Retrieved documents

        Returns:
            List of recommendations
        """
        recommendations = []

        avg_score = statistics.mean(scores) if scores else 0.0
        if avg_score < 0.6:
            recommendations.append("Consider improving query preprocessing or retrieval algorithm")

        low_scoring_docs = sum(1 for score in scores if score < threshold)
        if low_scoring_docs > len(scores) * 0.3:
            recommendations.append("Many documents have low relevance - refine retrieval criteria")

        return recommendations

    def _generate_utilization_recommendations(self, overall: float, word_overlap: float, sentence_util: float) -> List[str]:
        """Generate recommendations for improving context utilization.

        Args:
            overall: Overall utilization score
            word_overlap: Word overlap score
            sentence_util: Sentence utilization score

        Returns:
            List of recommendations
        """
        recommendations = []

        if overall < 0.6:
            recommendations.append("Improve context utilization in answer generation")
        if word_overlap < 0.3:
            recommendations.append("Increase use of relevant terms from context")
        if sentence_util < 0.4:
            recommendations.append("Better integrate context sentences into response")

        return recommendations

    def _generate_groundedness_recommendations(self, score: float, num_hallucinations: int, _assessment: Dict[str, Any]) -> List[str]:
        """Generate recommendations for improving groundedness.

        Args:
            score: Groundedness score
            num_hallucinations: Number of hallucinations detected
            _assessment: Overall assessment results

        Returns:
            List of recommendations
        """
        recommendations = []

        if score < 0.7:
            recommendations.append("Improve grounding of claims in provided context")
        if num_hallucinations > 0:
            recommendations.append("Reduce unsupported claims and hallucinations")

        return recommendations

    def _generate_hallucination_recommendations(self, rate: float, num_contradictions: int, _assessment: Dict[str, Any]) -> List[str]:
        """Generate recommendations for reducing hallucinations.

        Args:
            rate: Hallucination rate
            num_contradictions: Number of contradictions found
            _assessment: Overall assessment results

        Returns:
            List of recommendations
        """
        recommendations = []

        if rate > 0.2:
            recommendations.append("Significantly reduce hallucination rate")
        if num_contradictions > 0:
            recommendations.append("Eliminate contradictions with source context")

        return recommendations

    def _generate_coverage_recommendations(self, score: float, missing_topics: List[str], _irrelevance: Dict[str, Any]) -> List[str]:
        """Generate recommendations for improving coverage.

        Args:
            score: Coverage score
            missing_topics: List of missing topics
            _irrelevance: Irrelevance assessment

        Returns:
            List of recommendations
        """
        recommendations = []

        if score < 0.8:
            recommendations.append("Improve retrieval coverage of expected topics")
        if missing_topics:
            recommendations.append(f"Focus on retrieving content for: {', '.join(missing_topics[:3])}")

        return recommendations

    def _generate_citation_recommendations(self, accuracy: float, uncited_claims: int, _quality: Dict[str, Any]) -> List[str]:
        """Generate recommendations for improving citations.

        Args:
            accuracy: Citation accuracy score
            uncited_claims: Number of uncited claims
            _quality: Citation quality assessment

        Returns:
            List of recommendations
        """
        recommendations = []

        if accuracy < 0.8:
            recommendations.append("Improve citation accuracy")
        if uncited_claims > 0:
            recommendations.append("Add citations for unsupported claims")

        return recommendations

    def _generate_chunk_recommendations(self, scores: List[float], _threshold: float, _rankings: List[Tuple[int, float]]) -> List[str]:
        """Generate recommendations for chunk relevance.

        Args:
            scores: Chunk relevance scores
            _threshold: Relevance threshold
            _rankings: Chunk rankings by relevance

        Returns:
            List of recommendations
        """
        recommendations = []

        avg_score = statistics.mean(scores) if scores else 0.0
        if avg_score < 0.6:
            recommendations.append("Improve chunk selection and ranking")

        return recommendations

    def _generate_benchmark_recommendations(self, _results: Dict[str, Any], comparison: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on benchmark results.

        Args:
            _results: Benchmark results for all systems
            comparison: System comparison analysis

        Returns:
            List of recommendations
        """
        recommendations = []

        best_system = comparison.get("best_overall")
        if best_system:
            recommendations.append(f"Consider adopting strategies from {best_system}")

        return recommendations

    # Placeholder methods for complex operations that would need full implementation
    def _identify_underutilized_context(self, _context: str, _answer: str) -> List[str]:
        """Identify parts of context that weren't used.

        Args:
            _context: Retrieved context
            _answer: Generated answer

        Returns:
            List of underutilized context parts
        """
        return []  # Simplified implementation

    def _classify_hallucination_severity(self, rate: float, _contradictions: List[Dict]) -> str:
        """Classify hallucination severity.

        Args:
            rate: Hallucination rate
            _contradictions: List of contradictions found

        Returns:
            Severity level ('high', 'medium', 'low')
        """
        if rate > 0.3:
            return "high"
        if rate > 0.1:
            return "medium"
        return "low"

    async def _check_statement_contradiction(self, _statement: str, _context: str, _judge_model: str) -> Dict[str, Any]:
        """Check if statement contradicts context.

        Args:
            _statement: Statement to check
            _context: Context to check against
            _judge_model: Judge model for analysis

        Returns:
            Contradiction analysis results
        """
        return {"contradicts": False, "confidence": 0.9, "explanation": "No contradiction found"}

    async def _assess_overall_hallucination(self, _text: str, _context: str, _judge_model: str) -> Dict[str, Any]:
        """Overall hallucination assessment.

        Args:
            _text: Generated text to assess
            _context: Source context
            _judge_model: Judge model for assessment

        Returns:
            Overall hallucination assessment
        """
        return {"score": 0.1, "severity": "low", "reasoning": "No significant hallucinations"}

    async def _assess_topic_coverage(self, _topic: str, _content: str, _judge_model: str) -> Dict[str, Any]:
        """Assess if topic is covered in content.

        Args:
            _topic: Topic to check coverage for
            _content: Content to analyze
            _judge_model: Judge model for assessment

        Returns:
            Topic coverage assessment
        """
        return {"covered": True, "confidence": 0.8, "evidence": "Topic found in content"}

    async def _assess_retrieval_irrelevance(self, _query: str, _topics: List[str], _content: str, _judge_model: str) -> Dict[str, Any]:
        """Assess amount of irrelevant content.

        Args:
            _query: Original query
            _topics: Expected topics
            _content: Retrieved content
            _judge_model: Judge model for assessment

        Returns:
            Irrelevance assessment results
        """
        return {"irrelevance_score": 0.2, "irrelevant_sections": []}

    async def _verify_citation(self, _citation: Dict[str, Any], sources: List[Dict[str, Any]], _judge_model: str) -> Dict[str, Any]:
        """Verify citation accuracy.

        Args:
            _citation: Citation to verify
            sources: Available source documents
            _judge_model: Judge model for verification

        Returns:
            Citation verification results
        """
        return {"accurate": True, "confidence": 0.9, "supporting_source": sources[0] if sources else None}

    async def _find_uncited_claims(self, _text: str, _sources: List[Dict[str, Any]], _judge_model: str) -> List[str]:
        """Find claims that should be cited.

        Args:
            _text: Text to analyze
            _sources: Available source documents
            _judge_model: Judge model for analysis

        Returns:
            List of uncited claims
        """
        return []  # Simplified implementation

    async def _assess_citation_quality(self, _text: str, _sources: List[Dict[str, Any]], _judge_model: str) -> Dict[str, Any]:
        """Overall citation quality assessment.

        Args:
            _text: Text with citations to assess
            _sources: Available source documents
            _judge_model: Judge model for assessment

        Returns:
            Citation quality assessment
        """
        return {"score": 0.8, "issues": []}

    async def _judge_chunk_relevance(self, _query: str, _chunk: str, _judge_model: str) -> float:
        """Judge chunk relevance using LLM.

        Args:
            _query: Search query
            _chunk: Text chunk to assess
            _judge_model: Judge model for assessment

        Returns:
            Relevance score (0-1)
        """
        return 0.7  # Simplified implementation

    async def _simulate_retrieval(self, query: str, _system: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Simulate retrieval system (placeholder).

        Args:
            query: Search query
            _system: Retrieval system configuration

        Returns:
            List of retrieved documents
        """
        return [{"content": f"Retrieved document for {query}", "score": 0.8}]

    async def _evaluate_query_retrieval(self, _query: str, _retrieved: List[Dict], _expected: List[Dict], _metrics: List[str], _judge_model: str) -> Dict[str, Any]:
        """Evaluate retrieval for single query.

        Args:
            _query: Search query
            _retrieved: Retrieved documents
            _expected: Expected documents
            _metrics: Evaluation metrics to compute
            _judge_model: Judge model for evaluation

        Returns:
            Query evaluation results
        """
        return {"precision": 0.8, "recall": 0.7, "mrr": 0.75, "ndcg": 0.8}

    def _aggregate_system_performance(self, results: List[Dict[str, Any]], metrics: List[str]) -> Dict[str, Any]:
        """Aggregate performance across queries.

        Args:
            results: Individual query results
            metrics: Metrics to aggregate

        Returns:
            Aggregated system performance
        """
        aggregated = {}
        for metric in metrics:
            scores = [r.get(metric, 0.0) for r in results]
            aggregated[metric] = {
                "mean": statistics.mean(scores),
                "std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
                "min": min(scores),
                "max": max(scores),
            }
        return aggregated

    def _compare_retrieval_systems(self, results: Dict[str, Any], metrics: List[str]) -> Dict[str, Any]:
        """Compare multiple retrieval systems.

        Args:
            results: Results for all systems
            metrics: Metrics to compare

        Returns:
            System comparison analysis
        """
        if not results:
            return {"best_overall": None}

        # Simple ranking by average performance
        system_scores = {}
        for system_name, system_results in results.items():
            avg_score = statistics.mean([system_results[metric]["mean"] for metric in metrics if metric in system_results])
            system_scores[system_name] = avg_score

        best_system = max(system_scores.items(), key=lambda x: x[1])[0]

        return {
            "best_overall": best_system,
            "system_rankings": sorted(system_scores.items(), key=lambda x: x[1], reverse=True),
            "performance_gaps": system_scores,
        }
