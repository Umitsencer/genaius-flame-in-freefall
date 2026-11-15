# English jury presentation - five-minute script

The English deck is rebuilt for the supplied judging criteria. Seven slides including title/introduction. These times are rehearsal targets, not a measured recording: **30 + 40 + 40 + 45 + 45 + 60 + 40 = 300 seconds**. The deck also works as a silent demo: claims, sources, screenshots and limitations are on-slide.

Open `index.html` locally with its `assets/` folder, or share `genaius-presentation-en.pdf`. Arrow keys / PageUp / PageDown / Space navigate; Home / End jump; N shows cues; F enters fullscreen. The Turkish deck is the earlier page-oriented narrative and has not been updated to mirror this English revision.

## 1. A fire in space is not an Earth fire - 30 seconds

> We are Team GeNAIus, working on Flame in Freefall. When researchers study fire in a spacecraft, an Earth-based assumption or a nearby experiment may not describe the condition they need. NASA provides experimental evidence, but the relevant facts span tables, reports and different physical regimes. GeNAIus helps users find that evidence and distinguish four things: what was measured, what we calculated, what a model estimates, and what remains unsupported.

**Türkçe ipucu:** Problem veri yokluğu değil, uygun kanıta ulaşma ve bağlamı koruma. Ekip adları ilk slaytta.

## 2. Different experiments, different questions - 40 seconds

> NASA data is the foundation of our solution. BASS-II contributes 129 solid-material runs across 107 sample identifiers. FLEX contributes 274 liquid-droplet runs, with atmosphere, pressure, diameter and experiment-end information. Together these form our 403-run core, but we analyse each study within its own context. A broader catalog supports discovery across 24 studies. CFI, SAFFIRE-II and published SAFFIRE and SAME findings provide separate supporting evidence. We do not treat all catalog entries as fully integrated numerical datasets.

**Türkçe ipucu:** Katı ve sıvı deneylerini tek ortalamada karıştırmıyoruz. 24 katalog, 403 çekirdek koşu.

## 3. From question to actual test - 40 seconds

> Imagine a researcher comparing material measurements. In Material Lab, they select oxygen, material and shape, then inspect valid gas changes and their distribution. Each plotted point corresponds to a recorded test. Instead of ending at a chart or chatbot sentence, the workflow leads back to the test identifier, units and source location, with an exportable record. Missing or invalid measurements remain visible rather than becoming zeros. This is a comparison of evidence, not a ranking of safe materials.

**Türkçe ipucu:** Üç adım: seç, karşılaştır, kaynağı aç. Gerçek ekranı göster; zaman kazancı ölçtük deme.

## 4. Nearby is not the same - 45 seconds

> Next, ask whether PMMA at 34 percent oxygen has a matching test for a Moon habitat. The screenshot shows a gap in our indexed core, not proof that NASA has never tested such a condition. TESTED requires a recorded match to all supplied conditions. PARTIAL means material and oxygen match but another condition differs or is unrecorded. GAP means no material-and-oxygen match. The separate nearby-FLEX view can use a wider search window; it never upgrades a scenario to TESTED. The animation itself is conceptual, not a physical simulation.

**Türkçe ipucu:** ±2 yakın FLEX araması ile ±0,05 senaryo eşleşmesini karıştırma. GAP evrensel yokluk değil.

## 5. 344 seconds that need context - 45 seconds

> The case study shows why context matters. In the uncrewed Cygnus Saffire VI-3 experiment, ignition is reported at 637 seconds. The authors' selected one milligram per cubic metre smoke-concentration criterion is crossed at 981 seconds. We explicitly derive the 344-second difference. We do not call it an operational alarm delay or a crew exposure measurement. The interface connects these events to test conditions, gas results and the original report locations. The contribution is an inspectable case, not a claim of a new physical discovery.

**Türkçe ipucu:** 637 ve 981 raporlanmış, 344 türetilmiş. Alarmın çalışmadığını veya insanın zehirlendiğini söyleme.

## 6. Calculations outside the language model - 60 seconds

> Different tasks use different tools. Python calculates supported table answers and scenario coverage. BM25 retrieves report passages. An optional NVIDIA model through OpenRouter explains the supplied evidence; it does not replace the calculations. Schema, citation and numerical checks can reject a response and return deterministic evidence, though they cannot guarantee full semantic correctness. Separate scikit-learn models estimate FLEX burning-rate constant and score extinction. Recorded grouped validation gives regression R-squared of about 0.708. Classification has an important weakness: 32 of 82 non-extinction runs were falsely labelled extinction at the chosen threshold. We disclose that failure because these are research estimates, not spacecraft safety probabilities.

**Türkçe ipucu:** R² doğruluk yüzdesi değil. Model başarısızlığını saklamadan sınırını söyle. LLM isteğe bağlı; anahtar projede yok.

## 7. Contribution and impact - 40 seconds

> Our contribution is to connect evidence without hiding its boundaries. Researchers and engineering teams can compare measurements, trace claims, inspect coverage, and keep model estimates separate. This provides a starting point for evidence review and further experiment planning. We have not measured adoption or time savings, and this prototype does not certify spacecraft safety. Next, we would validate it with expert-reviewed questions, user studies and broader experimental coverage. The public project contains the source, data documentation and reproduction steps. Know what was tested. See what still needs evidence.

**Türkçe ipucu:** Etki hedefini ölçülmüş etki diye sunma. Sonraki adım uzman değerlendirmesi ve kullanıcı çalışması.

## Presentation and submission checks

- The user-supplied guide requires English slides, no more than seven including title, names, challenge and publicly accessible demo/project links.
- The guide describes a video alternative of at most 30 seconds; the five-minute live script is not a submission video.
- Ask an unauthenticated teammate to open the final PDF and repository. Repository push success is not a substitute for that access check.
- The local app requires setup; do not represent the repository as an already hosted web application.
- Scientific novelty, adoption, quantitative time savings and safety certification have not been established.
