# ConsentGuard

**Privacy-Preserving RAG and AI Agent Security Framework**

ConsentGuard is a research-oriented prototype for securing LLM-powered AI agents that interact with sensitive, multi-user healthcare records. It integrates deterministic consent-based authorization, an independent Security Gateway, authorization-scoped retrieval-augmented generation (RAG), and secure agent-tool interactions.

The central security principle is:

**The LLM proposes actions; an independent Security Gateway determines whether those actions are authorized.**

## Security Objectives

- **AI Agent Security:** Enforce deterministic authorization independently of LLM reasoning and tool selection.
- **RAG Security and Privacy:** Prevent unauthorized retrieval and cross-user data leakage through consent-aware access control.
- **Prompt Injection and Tool Security:** Restrict unauthorized tool operations through strict MCP argument validation and independent security enforcement.
- **Retrieval Memory Security:** Protect session-bound retrieval contexts through expiration and consent revalidation.

## System Architecture

ConsentGuard integrates:

1. **LLM Agent (LangGraph and OpenRouter):** Interprets user requests and proposes tool calls.
2. **Model Context Protocol (MCP):** Exposes controlled search and summarization tools.
3. **Security Gateway:** Validates tool arguments, enforces session-associated identity, and coordinates authorization.
4. **Consent Policy Engine (SQLite):** Evaluates record-level access permissions using consent directives.
5. **Secure Retrieval (ChromaDB):** Performs semantic similarity ranking over authorized record embeddings.
6. **Protected Retrieval Context:** Maintains temporary session-bound retrieval references and revalidates consent before returning record excerpts.

## Implemented Security Mechanisms

- Deterministic, default-deny authorization independent of LLM decisions.
- Consent-aware filtering before retrieving documents from the vector database.
- Strict MCP tool-argument validation, including rejection of identity-spoofing parameters.
- Session-bound retrieval references with expiration.
- Consent revalidation before releasing previously retrieved record excerpts.
- Fail-closed handling of invalid authorization and retrieval operations.
- Automated tests covering selected consent-policy and MCP security scenarios.

## Research Evaluation Roadmap

The next phase will investigate:

- **Prompt Injection:** Attempts to manipulate agent behavior through user inputs and malicious retrieved documents.
- **Cross-User Data Leakage:** Attempts to access records belonging to unauthorized users.
- **Memory Poisoning:** Manipulation of retrieval contexts and agent memory.
- **Tool-Call Security:** Attempts to bypass authorization through MCP tool interfaces.
- **Security Benchmarking:** Evaluation of protection effectiveness and performance overhead.

Planned evaluation metrics include attack success rate (ASR), unauthorized disclosure rate, authorization decision precision and recall, and Security Gateway latency overhead.

## Current Limitations

ConsentGuard is a research prototype using synthetic healthcare records. It currently relies on controlled test identities rather than production authentication. The summarization tool provides extractive excerpts rather than full clinical synthesis. Comprehensive adversarial benchmarking, dedicated data-poisoning defenses, and production deployment hardening remain future work.

## Technology Stack

Python, LangGraph, OpenRouter, Model Context Protocol (MCP), SQLite, ChromaDB, NumPy.

## Research Background and Reference

ConsentGuard builds upon prior research on consent-based access control (CBAC) for healthcare information systems:

**[1]** N. Muslim and J.-C. Grégoire, "An Extended Consent-Based Access Control Framework: Pre-Commit Validation and Emergency Access," *arXiv preprint arXiv:2603.07004*, 2026.

**Paper:** https://arxiv.org/abs/2603.07004

**DOI:** https://doi.org/10.48550/arXiv.2603.07004

The underlying research introduces pre-commit consent conflict analysis, formalizes baseline access rights for patients and record authors, and proposes controlled emergency access mechanisms.

ConsentGuard extends this research direction toward deterministic authorization for LLM-based AI agents. The current implementation covers a subset of the original framework and does not implement its full emergency-access mechanism.
