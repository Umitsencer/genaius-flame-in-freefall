# AI use and verification

## Retrieval and calculations

Core table queries, scenario checks and descriptive answers are deterministic. Document retrieval uses a custom Okapi BM25 implementation over source-located report chunks. There is no embedding model, vector database or neural reranker in the active stack.

BM25 ranks lexical relevance. The 24-study catalog uses deterministic metadata field matching. Neither score represents scientific quality or fire safety.

Coverage badges distinguish **MATCHING TESTS FOUND**, **RELATED TESTS ONLY**, **NO MATCH IN INDEXED SOURCES** and **SOURCE UNAVAILABLE / ERROR**. A source loading failure is not an evidence gap. The scenario panel's separate `TESTED / PARTIAL / GAP` labels likewise describe indexed coverage, not safety.

## Optional LLM

An OpenRouter adapter can synthesize a short explanation from a bounded evidence bundle. It is enabled through local environment variables or `.env`; its default model ID is `nvidia/nemotron-3.5-super-vl:free`. Only explicitly named `:free` models are accepted. Provider quotas, availability, retention and terms remain external conditions.

Page loads, chart controls, exports, table calculations, scenario checks and FLEX predictions do not invoke an LLM. Supported table-answer routes bypass it even when enabled.

## Output checks

1. Bound the question and evidence payload.
2. Supply allowed table/document/model citation IDs.
3. Require a strict Pydantic answer schema.
4. Check citation membership and numerical/unit consistency in the summary and findings.
5. Reject invalid output and show explicitly labelled deterministic evidence instead.

These checks do not guarantee full semantic truth, freedom from prompt injection or complete scientific interpretation. A source hash proves file identity; a permitted citation does not prove that every sentence is supported.

## Models are separate

FLEX Ridge regression and logistic classification are pre-fitted statistical models. They do not generate the conceptual animation and are not language models. Model estimates, reported measurements and derived quantities are labelled separately.

## Privacy

When an LLM question is submitted, the question and relevant public evidence are sent to OpenRouter and its selected provider. Do not submit confidential information. The app does not promise provider-side zero retention. API keys are kept outside Git; HTTP access logs are disabled by the local server.

AI coding assistants helped develop and review this project. Scientific claims must be checked against source data, code and evaluation artifacts rather than accepted from generated prose.
