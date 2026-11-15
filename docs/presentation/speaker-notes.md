# GeNAIus — five-minute jury presentation

Slides and the spoken script below are in English. Times are targets, not a measured recording. Rehearse once and adjust pauses rather than rushing. The deck contains seven slides: **35 + 40 + 50 + 45 + 40 + 50 + 40 = 300 seconds**.

Open `index.html` (English) or `index-tr.html` (Turkish) in Chrome/Edge. Arrow keys, PageUp/PageDown or Space navigate; Home/End jump; **N** toggles presenter cues; **F** enters fullscreen. The two language-specific PDFs contain slides only, without presenter notes. Turkish rehearsal cues below are for the presenters.

## 1. Problem and solution — 35 seconds

> Fire behaves differently in microgravity. Buoyancy-driven flow is greatly reduced, so ignition, flame shape and extinction can differ from what we expect on Earth. NASA has decades of experiments, but the evidence is spread across tables and reports. GeNAIus helps researchers find the relevant study, compare actual measurements, and trace a result back to its source. Our contribution is a clearer path through the evidence, with its limits visible.

**Türkçe ipucu:** Dağınık veri → ilgili deney → kaynaklı sonuç. Yeni fizik keşfi iddiası yok.

## 2. Material Lab — 40 seconds

> Material Lab uses 129 BASS-II runs across 107 unique sample identifiers. We choose the oxygen level, material and geometry, then inspect measured gas changes. Each point represents a test. The charts show the distribution of valid readings, while the coverage view shows where tests are missing. Missing or invalid endpoints are not turned into zero. We can open the actual record behind a result. This supports evidence comparison, not a ranking of the safest material.

**Türkçe ipucu:** Bir nokta = bir deney. Medyan ve dağılımı anlat; regresyon burada değil.

## 3. Fire, scenarios and models — 50 seconds

> The animation provides a conceptual view of droplet burning. It is not CFD or a measured video replay. The scenario checker has a separate job: compare selected conditions with indexed table records. TESTED, PARTIAL and GAP describe evidence coverage. For example, PMMA at 34 percent oxygen under a Moon-like scenario gives GAP in our indexed core; that does not mean NASA never tested it. We also provide two separate FLEX models: Ridge estimates the burning-rate constant, and logistic regression gives an uncalibrated extinction score. Both are restricted by experimental support and are distinct from measured NASA results.

**Türkçe ipucu:** Animasyon / kapsam / tahmin üç ayrı işlev. Toleranslar ±0,05 O₂ yüzde puanı, ±0,01 atm. Modeller için güvenlik olasılığı deme.

## 4. SAFFIRE case study — 45 seconds

> Our case study follows a real fire experiment in an uncrewed Cygnus spacecraft. In VI-3, ignition is reported at 637 seconds. The authors' selected one milligram per cubic metre smoke-concentration criterion is crossed at 981 seconds. We calculate the 344-second interval between these timestamps. This is not an operational alarm-latency measurement. The reported burn duration of 780 seconds is shown separately from the fan shutdown. Conditions, gas increases and source pages remain linked, and unpublished gas values for V-3 and V-4 remain missing.

**Türkçe ipucu:** 637 ve 981 raporlanmış; 344 hesaplanmış. 780 saniyeyi fan kapanışıyla karıştırma.

## 5. Data and traceability — 40 seconds

> The catalog contains 24 studies, but catalog coverage is not full numerical integration. Our core contains 403 runs: 129 BASS-II and 274 FLEX. CFI and SAFFIRE-II are separate modules. Users can compare selected records and export the same filtered subset. A record retains its raw value, unit, status, source line and file fingerprint. The fingerprint identifies the source file; it does not prove scientific truth. This makes the analysis inspectable and helps researchers reuse the evidence responsibly.

**Türkçe ipucu:** 24 çalışma ≠ 403 tam entegre araştırma. Kaynak satırı ve dosya kimliği.

## 6. Evidence assistant and technical engine — 50 seconds

> Table questions are calculated directly from eligible records. Report questions use BM25 lexical retrieval; there is no embedding model or vector database in this version. When enabled, the NVIDIA model through OpenRouter receives a bounded evidence bundle and produces an explanation. Its schema, citations, numbers and units are checked. Invalid output is rejected in favour of deterministic evidence. This reduces specific errors but does not guarantee full semantic correctness. FastAPI and Pydantic support the backend; JavaScript, SVG and Canvas support the interface. Some chart statistics are calculated in the browser. FLEX training uses scikit-learn and grouped cross-validation.

**Türkçe ipucu:** LLM durumu demo makinesine bağlı. Anahtar yoksa deterministik cevaplar çalışır. Model adı yerine kanıttaki rolünü vurgula.

## 7. Contribution and close — 40 seconds

> GeNAIus addresses the challenge through three contributions. First, it helps users find relevant combustion research. Second, it provides traceable data and separate statistical estimates to support modelling. Third, it makes gaps visible before users transfer findings to unsupported conditions. The intended users are combustion researchers and spacecraft or habitat engineering teams reviewing evidence. This is a research prototype, not a certification tool. Know what was tested. See what is missing. Trace every claim.

**Türkçe ipucu:** Üç katkıyı challenge'a bağla. Son üç cümleyi yavaş söyle.

## Optional live demo questions

- `What was the highest oxygen level tested on solid materials?` — deterministic PSI-25 table answer.
- `What happened in Saffire VI-3?` — case-scoped evidence; optional LLM if configured.
- `Was PMMA at 34% oxygen tested for a Moon habitat?` — indexed coverage gap, not a universal claim.

Check the actual LLM badge before presenting. Do not claim that the clean public installation includes a key or always produces model-written answers.
