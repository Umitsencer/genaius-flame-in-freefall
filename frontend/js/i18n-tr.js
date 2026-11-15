/* Turkish text for the pages (see i18n.js). Pairs are [english, turkish]. {} matches any text, {#} a number; the Turkish side
 * uses {1}, {2} ... for the matches in order. Plain strings must match the page's English text exactly. */
(function () {
  'use strict';
  var I = FF.i18n;

  /* ---------- words that appear inside longer patterns ---------- */
  I.words([
    ['Methanol', `Metanol`], ['methanol', `metanol`], ['Heptane', `Heptan`], ['heptane', `heptan`], ['Helium', `Helyum`], ['helium', `helyum`],
    ['Extinction', `Sönme`], ['extinction', `sönme`], ['Disruption', `Parçalanma`], ['disruption', `parçalanma`], ['Completion', `Tamamlanma`], ['completion', `tamamlanma`],
    ['Starting oxygen', `Başlangıç oksijeni`], ['Oxygen change', `Oksijen değişimi`], ['oxygen change', `oksijen değişimi`],
    ['CO₂ change', `CO₂ değişimi`], ['CO change', `CO değişimi`], ['Oxygen', `Oksijen`], ['oxygen', `oksijen`], ['Pressure', `Basınç`], ['pressure', `basınç`],
    ['Air flow', `Hava akışı`], ['air flow', `hava akışı`], ['Burn time', `Yanma süresi`], ['burn time', `yanma süresi`],
    ['Approximate', `Yaklaşık`], ['Range or list', `Aralık veya liste`], ['Invalid', `Geçersiz`], ['No number in source', `Kaynakta sayı yok`], ['Not recorded', `Kaydedilmedi`], ['Not in this table', `Bu tabloda yok`], ['Measured', `Ölçüldü`],
    ['very strong positive', `çok güçlü pozitif`], ['very strong negative', `çok güçlü negatif`], ['strong positive', `güçlü pozitif`], ['strong negative', `güçlü negatif`],
    ['moderate positive', `orta düzeyde pozitif`], ['moderate negative', `orta düzeyde negatif`], ['weak positive', `zayıf pozitif`], ['weak negative', `zayıf negatif`], ['very weak', `çok zayıf`]
  ]);

  /* ---------- exact strings ---------- */
  var T = [
    ['Statistics across all filtered runs.', `Tüm filtrelenmiş deneylerin istatistikleri.`],
    ['Test records and sources.', `Deney kayıtları ve kaynakları.`],
    ['Conceptual animation from FLEX summaries.', `FLEX özetleriyle kavramsal animasyon.`],
    ['Conditions and calculated oxygen pressure.', `Koşullar ve hesaplanan oksijen basıncı.`],
    ['Reported airflow changes.', `Kayıtlı hava akışı değişimleri.`],
    ['Gas increases, not crew exposure.', `Gaz artışları; mürettebat maruziyeti değil.`],
    ['Gas and heat; missing stays missing.', `Gaz ve ısı; eksikler korunur.`],
    ['Ignition to smoke criterion: derived 344 s.', `Ateşlemeden duman ölçütüne: hesaplanan 344 sn.`],
    ['Particle size and detection limits.', `Parçacık boyutu ve algılama sınırları.`],
    ['Original reports and source pages.', `Özgün raporlar ve kaynak sayfaları.`],
    ['Studies and integration levels.', `Araştırmalar ve entegrasyon düzeyleri.`],
    ['Condition comparison, not safety ranking.', `Koşul karşılaştırması; güvenlik sıralaması değil.`],
    ['Valid measurements and exclusions.', `Geçerli ölçümler ve dışlananlar.`],
    ['Cool flames by pressure and fiber.', `Basınç ve life göre soğuk alevler.`],
    ['Nine samples and source caveats.', `Dokuz numune ve kaynak sınırlılıkları.`],
    ['BM25 word relevance, not scientific validation.', `BM25 sözcük ilgisi; bilimsel doğrulama değil.`],
    ['Evidence, gaps and engineering interpretation.', `Kanıt, boşluklar ve mühendislik yorumu.`],
    ['Source locations and file hashes.', `Kaynak konumları ve dosya özetleri.`],
    ['Habitat coverage in indexed tables.', `Yaşam alanı koşullarının veri kapsamı.`],
    ['Nearest tests and condition differences.', `En yakın deneyler ve koşul farkları.`],
    ['Coverage, not safety.', `Kanıt kapsamı; güvenlik değil.`],
    ['Test coverage and nearby medians.', `Test kapsamı ve yakın medyanlar.`],
    ['Measured relationships, not causation.', `Ölçümler arası ilişki; nedensellik değil.`],
    ['Median and spread.', `Medyan ve dağılım.`],
    ['Two oxygen ranges compared.', `İki oksijen aralığının karşılaştırması.`],
    ['Test counts and data gaps.', `Test sayıları ve veri boşlukları.`],
    // navigation, titles, skip links
    ['Material lab', `Malzeme laboratuvarı`], ['Fire animation', `Yangın animasyonu`], ['Data', `Veri`], ['Sources', `Kaynaklar`], ['Coming soon', `Yakında`], ['Lab', `Lab`], ['Fire', `Yangın`],
    ['Material lab | Flame in Freefall', `Malzeme laboratuvarı | Flame in Freefall`], ['Data | Flame in Freefall', `Veri | Flame in Freefall`], ['Fire animation | Flame in Freefall', `Yangın animasyonu | Flame in Freefall`],
    ['Skip to the analysis', `Analize geç`], ['Skip to the data', `Veriye geç`], ['Main', `Ana menü`], ['GeNAIus, home', `GeNAIus, ana sayfa`], ['Sections', `Bölümler`], ['Filters', `Filtreler`],
    // assistant
    ['Evidence assistant', `Kanıt asistanı`], ['Open the evidence assistant', `Kanıt asistanını aç`],
    ['NASA PSI grounded evidence assistant', `NASA PSI kanıt temelli asistan`],
    ['OpenRouter :free + deterministic NASA fallback', `OpenRouter :free + deterministik NASA yedeği`],
    ['Offline deterministic NASA evidence (LLM disabled)', `Çevrimdışı deterministik NASA kanıtı (LLM kapalı)`],
    ['Deterministic NASA evidence answers (No LLM)', `Deterministik NASA kanıt yanıtları (LLM yok)`],
    ['Guardrail · Not sent to LLM', `Korkuluk · LLM'e gönderilmedi`],
    ['Deterministic · Guardrail', `Deterministik · Korkuluk`],
    ['Deterministic · No LLM', `Deterministik · LLM yok`],
    ['OpenRouter LLM · Cited only', `OpenRouter LLM · Yalnız kaynaklı`],
    ['Fallback -> Deterministic (LLM unavailable)', `Yedek -> Deterministik (LLM kullanılamıyor)`],
    ['Fallback -> Deterministic (No LLM)', `Yedek -> Deterministik (LLM yok)`],
    ['Technical details', `Teknik ayrıntılar`],
    ['Numerical consistency checked (summary & findings)', `Sayısal tutarlılık denetlendi (özet ve bulgular)`],
    ['Synthesis scope: isolated SAFFIRE IV–VI / SAME case bundle only (core 403, PSI-39 CFI, PSI-99 SAFFIRE-II excluded).', `Sentez kapsamı: yalnızca izole SAFFIRE IV–VI / SAME vaka paketi (çekirdek 403, PSI-39 CFI ve PSI-99 SAFFIRE-II hariç).`],
    ['Synthesis scope: FLEX prediction support gate + nearest PSI-69 tests only.', `Sentez kapsamı: yalnızca FLEX tahmin destek kapısı + en yakın PSI-69 testleri.`],
    ['Synthesis scope: retrieved PSI-25/PSI-69 evidence bundle only (CFI and SAFFIRE-II excluded).', `Sentez kapsamı: yalnızca getirilen PSI-25/PSI-69 kanıt paketi (CFI ve SAFFIRE-II hariç).`],
    ['LLM draft rejected by schema/citation validation. Showing deterministic NASA records below (no LLM synthesis).', `LLM taslağı şema/atıf doğrulamasından geçemedi. Aşağıda deterministik NASA kayıtları gösteriliyor (LLM sentezi yok).`],
    ['LLM draft rejected by numerical/unit check. Showing deterministic NASA records below (no LLM synthesis).', `LLM taslağı sayısal/birim denetiminden geçemedi. Aşağıda deterministik NASA kayıtları gösteriliyor (LLM sentezi yok).`],
    ['OpenRouter returned HTTP 429 (rate limit). Showing deterministic NASA records below (no LLM synthesis).', `OpenRouter HTTP 429 (istek sınırı) döndürdü. Aşağıda deterministik NASA kayıtları gösteriliyor (LLM sentezi yok).`],
    ['LLM provider unavailable. Showing deterministic NASA records below (no LLM synthesis).', `LLM sağlayıcısına ulaşılamıyor. Aşağıda deterministik NASA kayıtları gösteriliyor (LLM sentezi yok).`],
    ['LLM output unavailable or rejected. Showing deterministic NASA records below (no LLM synthesis).', `LLM çıktısı alınamadı veya reddedildi. Aşağıda deterministik NASA kayıtları gösteriliyor (LLM sentezi yok).`],
    ['Auto (Smart route)', `Otomatik (Akıllı kapsam)`],
    ['Core (PSI-25 + PSI-69)', `Çekirdek (PSI-25 + PSI-69)`],
    ['SAFFIRE IV–VI Case Study', `SAFFIRE IV–VI Vaka İncelemesi`],
    ['FLEX Predictor (Active condition)', `FLEX Tahminleyici (Etkin koşul)`],
    ['Searching NASA evidence and documents...', `NASA kanıtları ve belgeleri aranıyor...`],
    ['Ask a question about the NASA tests', `NASA testleri hakkında bir soru sorun`], ['Ask about the NASA tests', `NASA testlerini sorun`], ['Send', `Gönder`], ['Close', `Kapat`], ['Retry', `Tekrar dene`],
    ['Try an example', `Bir örnek deneyin`],
    ['Ask a question about the NASA PSI combustion evidence. Supported answers cite exact test rows and documents, and unsupported extrapolations explicitly abstain.', `NASA PSI yanma kanıtları hakkında bir soru sorun. Desteklenen yanıtlar tam test satırlarını ve belgeleri kaynak gösterir; desteklenmeyen çıkarımlarda açıkça çekinir.`],
    ['No answer was returned.', `Cevap gelmedi.`], ['The evidence assistant is unavailable right now.', `Kanıt asistanı şu an kullanılamıyor.`],
    // shared words
    ['Environment', `Ortam`], ['Experiment', `Deney`], ['Experiments', `Deneyler`], ['experiment', `deney`], ['experiments', `deney`], ['Material', `Malzeme`], ['Material and shape', `Malzeme ve şekil`], ['Shape', `Şekil`],
    ['Oxygen', `Oksijen`], ['Pressure', `Basınç`], ['Gravity', `Yerçekimi`], ['Air flow', `Hava akışı`], ['Burn time', `Yanma süresi`], ['Burning rate', `Yanma hızı`], ['Fuel', `Yakıt`], ['Diluent', `Seyreltici`],
    ['Test', `Test`], ['Tests', `Test`], ['Source', `Kaynak`], ['Status', `Durum`], ['Field', `Alan`], ['Unit', `Birim`], ['Group', `Grup`], ['Group by', `Grupla`], ['Platform', `Platform`], ['Rows', `Satır`], ['File', `Dosya`], ['License', `Lisans`],
    ['Any', `Herhangi`], ['Custom', `Özel`], ['Search', `Ara`], ['Clear', `Temizle`], ['Remove', `Çıkar`], ['Compare', `Karşılaştır`], ['Cite', `Alıntıla`], ['Show', `Göster`], ['Speed', `Hız`], ['Half', `Yarım`], ['Normal', `Normal`], ['Double', `Çift`],
    ['Play', `Oynat`], ['Pause', `Duraklat`], ['Replay', `Tekrar oynat`], ['Copy link', `Bağlantıyı kopyala`], ['Copy link to this view', `Bu görünümün bağlantısını kopyala`], ['Reset filters', `Filtreleri sıfırla`], ['Save chart', `Grafiği kaydet`],
    ['Show all', `Tümünü göster`], ['Show fewer', `Daha az göster`], ['Clear selection', `Seçimi temizle`], ['Clear comparison', `Karşılaştırmayı temizle`], ['Add to comparison', `Karşılaştırmaya ekle`], ['Remove from comparison', `Karşılaştırmadan çıkar`],
    ['Cite this row', `Bu satırı alıntıla`], ['Copy citation', `Alıntıyı kopyala`], ['Copy BibTeX', `BibTeX'i kopyala`], ['See the comparison', `Karşılaştırmaya bak`], ['see the comparison', `karşılaştırmaya bakın`],
    ['Methanol', `Metanol`], ['Heptane', `Heptan`], ['Helium', `Helyum`], ['Extinction', `Sönme`], ['Disruption', `Parçalanma`], ['Completion', `Tamamlanma`], ['Both fuels', `İki yakıt`], ['Outcome', `Sonuç`],
    ['Concurrent', `Eş yönlü`], ['Opposed', `Karşıt yönlü`], ['Prevention', `Önleme`], ['Detection', `Algılama`], ['Suppression', `Söndürme`], ['Fundamental combustion', `Temel yanma`],
    ['SIBAL fabric', `SIBAL kumaş`], ['Silicone', `Silikon`], ['Wax candle', `Mum`], ['ultem sheet', `Ultem levha`], ['PMMA rod', `PMMA çubuk`], ['PMMA slab', `PMMA levha`], ['PMMA film', `PMMA film`], ['PMMA sphere', `PMMA küre`], ['fabric', `kumaş`],
    ['Measured', `Ölçüldü`], ['Approximate', `Yaklaşık`], ['Range or list', `Aralık veya liste`], ['Invalid', `Geçersiz`], ['No number in source', `Kaynakta sayı yok`], ['Not recorded', `Kaydedilmedi`], ['Not in this table', `Bu tabloda yok`],
    ['not in table', `tabloda yok`], ['not in this table', `bu tabloda yok`], ['not recorded', `kaydedilmedi`], ['not numeric', `sayısal değil`], ['over range', `sınırın üstünde`], ['none', `yok`], ['empty', `boş`], ['other', `diğer`],
    ['no such column', `böyle bir sütun yok`], ['none in table', `tabloda yok`], ['not named', `adı yok`], ['differs', `farklı`], ['few', `az`], ['too few', `çok az`], ['Not BASS-II', `BASS-II değil`],
    ['tests shown', `test gösteriliyor`], ['test shown', `test gösteriliyor`], ['rows carry a data note', `satırda veri notu var`], ['with no oxygen level recorded', `oksijen düzeyi kaydı olmayan`], ['highest oxygen tested', `test edilen en yüksek oksijen`],
    ['with a CO change reading', `CO değişimi ölçümü olan`], ['with a CO₂ change reading', `CO₂ değişimi ölçümü olan`], ['with an oxygen change reading', `oksijen değişimi ölçümü olan`], ['with a oxygen change reading', `oksijen değişimi ölçümü olan`],
    ['median burn time', `ortanca yanma süresi`], ['median droplet width when the flame went out', `alev sönerken ortanca damlacık genişliği`],

    // ---- Material lab ----
    ['Which materials has NASA burned in microgravity, at what oxygen levels, and what did the gas readings show? Choose an oxygen level on the left, then read the charts below.', `NASA mikroyerçekiminde hangi malzemeleri, hangi oksijen düzeylerinde yaktı ve gaz ölçümleri ne gösterdi? Soldan bir oksijen düzeyi seçin, sonra aşağıdaki grafikleri okuyun.`],
    ['Oxygen preset', `Oksijen ön ayarı`], ['Air, 21%', `Hava, %21`], ['Exploration atmosphere, 34%', `Keşif atmosferi, %34`], ['Normal air, as on the ISS.', `Normal hava, ISS'teki gibi.`],
    ['The planned exploration atmosphere has 34% oxygen. Its pressure is not used here because these tests do not record it.', `Planlanan keşif atmosferinde %34 oksijen var. Bu testlerde basınç kaydedilmediği için basıncı burada kullanmıyoruz.`],
    ['Use the slider to set any oxygen level.', `Herhangi bir oksijen düzeyi için kaydırıcıyı kullanın.`], ['What counts as near', `Neyin yakın sayılacağı`],
    ['Pressure and gravity are not recorded in these test tables, so they do not change any chart here.', `Basınç ve yerçekimi bu test tablolarında kayıtlı olmadığı için buradaki hiçbir grafiği değiştirmez.`],
    ['Measure', `Ölçüm`], ['Gas reading to compare', `Karşılaştırılacak gaz ölçümü`], ['CO change (ppm)', `CO değişimi (ppm)`], ['Oxygen change (vol%)', `Oksijen değişimi (hacim %)`], ['CO₂ change (vol%)', `CO₂ değişimi (hacim %)`],
    ['Airflow restriction (BASS-II)', `Hava akışı kısıtlaması (BASS-II)`], ['0, least restricted', `0, en az kısıtlı`], ['2, most restricted', `2, en çok kısıtlı`], ['Investigator (BASS-II)', `Araştırmacı (BASS-II)`], ['Investigator', `Araştırmacı`],
    ['Evidence map', `Kanıt haritası`], ['Compare measures', `Ölçümleri karşılaştır`], ['Spread', `Dağılım`], ['By oxygen band', `Oksijen aralığına göre`], ['Two ranges', `İki aralık`], ['Coverage', `Kapsam`], ['Statistics', `İstatistikler`], ['All tests', `Tüm testler`],
    ['Spread & statistics', `Dağılım ve istatistikler`], ['Oxygen comparisons', `Oksijen karşılaştırmaları`],
    ['These statistics use all filtered runs. The nearby-oxygen checkbox applies only to the distribution chart above.', `Bu istatistikler filtrelerden geçen tüm koşuları kullanır. Oksijeninize yakın testler kutusu yalnızca yukarıdaki dağılım grafiğini etkiler.`],
    ['Change what counts as near in the left panel. These are test readings, not a safety rating.', `Neyin yakın sayılacağını sol panelden değiştirin. Bunlar test ölçümleridir, güvenlik derecelendirmesi değildir.`],
    ['Each dot is one test at its starting oxygen. The red line is your setting and the amber area is oxygen nobody tested. The right column is the median gas reading among tests within the window you chose. Rows with at least three readings come first, lowest reading first. This orders readings, not safety.', `Her nokta, başlangıç oksijeninde yapılmış bir testtir. Kırmızı çizgi sizin ayarınız, sarı alan ise kimsenin test etmediği oksijen aralığıdır. Sağ sütun, seçtiğiniz pencere içindeki testlerin gaz ölçümü medyanıdır. En az üç ölçümü olan satırlar önce gelir, en düşük ölçüm en başta. Bu, güvenliği değil ölçümleri sıralar.`],
    ['Compare any two measures', `Herhangi iki ölçümü karşılaştırın`],
    ['Pick what goes on each axis. Hover a dot to see the test, click it to pin it, and click a legend name to hide a group.', `Her eksene ne geleceğini seçin. Testi görmek için noktanın üstüne gelin, sabitlemek için tıklayın, bir grubu gizlemek için gösterge adına tıklayın.`],
    ['Across', `Yatay`], ['Up', `Dikey`], ['Colour by', `Renklendir`], ['Starting oxygen', `Başlangıç oksijeni`], ['Oxygen change', `Oksijen değişimi`], ['CO₂ change', `CO₂ değişimi`], ['CO change', `CO değişimi`], ['Airflow restriction', `Hava akışı kısıtlaması`], ['Band medians', `Aralık medyanları`],
    ['Starting oxygen (%)', `Başlangıç oksijeni (%)`], ['CO change (ppm, final minus initial)', `CO değişimi (ppm, son eksi ilk)`], ['Oxygen change (vol%, final minus initial)', `Oksijen değişimi (hacim %, son eksi ilk)`], ['CO₂ change (vol%, final minus initial)', `CO₂ değişimi (hacim %, son eksi ilk)`],
    ['Median CO change (ppm, final minus initial)', `Ortanca CO değişimi (ppm, son eksi ilk)`], ['Median Oxygen change (vol%, final minus initial)', `Ortanca oksijen değişimi (hacim %, son eksi ilk)`], ['Median CO₂ change (vol%, final minus initial)', `Ortanca CO₂ değişimi (hacim %, son eksi ilk)`],
    ['Rank correlation', `Sıra korelasyonu`], ['Too few pairs to measure how the two move together.', `İkisinin birlikte nasıl değiştiğini ölçmek için çok az çift var.`],
    ['How the readings spread', `Ölçümler nasıl dağılıyor`],
    ['The box holds the middle half of the tests, the thick bar is the median, and the thin line reaches the typical extremes. Wide boxes mean tests of the same material gave very different readings.', `Kutu testlerin orta yarısını içerir, kalın çubuk medyandır, ince çizgi tipik uçlara kadar uzanır. Geniş kutular, aynı malzemenin testlerinin çok farklı ölçümler verdiği anlamına gelir.`],
    ['Only tests near your oxygen', `Yalnızca oksijeninize yakın testler`], ['Median by oxygen band', `Oksijen aralığına göre medyan`],
    ['Each marker is the median of the tests in one oxygen band and the bar shows their middle half. Hollow markers have fewer than three tests. Comparing within one group avoids mixing sample shapes.', `Her işaret, bir oksijen aralığındaki testlerin medyanıdır, çubuk ise orta yarılarını gösterir. İçi boş işaretlerde üçten az test vardır. Tek bir grup içinde karşılaştırmak, farklı numune şekillerinin karışmasını önler.`],
    ['Band width', `Aralık genişliği`], ['Oxygen in the test chamber (%)', `Test odasındaki oksijen (%)`], ['Two oxygen ranges, side by side', `İki oksijen aralığı, yan yana`],
    ['Filled markers are the first range, hollow markers the second. A long line means the reading changed a lot between them.', `Dolu işaretler birinci aralık, boş işaretler ikinci aralıktır. Uzun bir çizgi, ölçümün ikisi arasında çok değiştiği anlamına gelir.`],
    ['First oxygen range (%)', `Birinci oksijen aralığı (%)`], ['Second oxygen range (%)', `İkinci oksijen aralığı (%)`],
    ['No group has at least 3 tests in both ranges. Widen the ranges or pick ranges that were actually tested.', `Hiçbir grubun iki aralıkta da en az 3 testi yok. Aralıkları genişletin ya da gerçekten test edilmiş aralıklar seçin.`],
    ['Coverage', `Kapsam`], ['How many tests exist for each group and 2-point oxygen band. Dashed empty cells are gaps, and amber columns are above the highest oxygen ever tested here. The outlined column is your setting.', `Her grup ve 2 puanlık oksijen aralığı için kaç test olduğu. Kesikli boş hücreler boşluktur, sarı sütunlar burada şimdiye kadar test edilen en yüksek oksijenin üstündedir. Çerçeveli sütun sizin ayarınızdır.`],
    ['Oxygen band starts at (%)', `Oksijen aralığının başlangıcı (%)`], ['Summary statistics', `Özet istatistikler`], ['The numbers behind the charts, for the measure and grouping you chose.', `Seçtiğiniz ölçüm ve gruplama için grafiklerin arkasındaki sayılar.`],
    ['Mean', `Ortalama`], ['Median', `Medyan`], ['Middle half', `Orta yarı`], ['Lowest', `En düşük`], ['Highest', `En yüksek`], ['Moves with oxygen', `Oksijenle birlikte değişir`],
    ['Every test that passes your filters. Click a header to sort and a row to pin it in the charts.', `Filtrelerinizden geçen her test. Sıralamak için bir başlığa, grafiklerde sabitlemek için bir satıra tıklayın.`], ['Download these tests as CSV', `Bu testleri CSV olarak indir`],
    ['Oxygen %', `Oksijen %`], ['CO₂ change', `CO₂ değişimi`], ['CO change ppm', `CO değişimi ppm`],
    [`Data: NASA Physical Sciences Informatics, PSI-25 BASS-II (129 microgravity runs across 107 unique Sample # specimens), public domain (CC0). Gas change is final minus initial reading only when both endpoints are measured. Negative invalid CO readings and above-limit (>1000 ppm) readings are explicitly excluded and never coerced to zero. Condition comparison only — does not rate flammability or fire safety.`, `Veri: NASA Physical Sciences Informatics, PSI-25 BASS-II (107 benzersiz Sample # örneği üzerinde 129 mikroyerçekimi koşusu), kamu malı (CC0). Gaz değişimi yalnızca iki uç da ölçüldüğünde son eksi ilk değerdir. Geçersiz negatif CO ve sınır üstü (>1000 ppm) okumalar açıkça dışlanır, asla sıfıra çevrilmez. Yalnızca koşul karşılaştırmasıdır — yanıcılık veya yangın güvenliği derecelendirmesi yapmaz.`],
    ['Team GeNAIus, NASA Space Apps Challenge 2026.', `Takım GeNAIus, NASA Space Apps Challenge 2026.`], ['Team GeNAIus, NASA Space Apps Challenge 2026, Kırklareli.', `Takım GeNAIus, NASA Space Apps Challenge 2026, Kırklareli.`],
    ['Nothing here was tested near {} oxygen.', `Burada hiçbir şey {1} oksijen civarında test edilmedi.`],
    ['Neither range has tests for the current filters.', `Mevcut filtrelerle iki aralıkta da test yok.`], ['No bands have enough tests for the current filters.', `Mevcut filtrelerle yeterli testi olan aralık yok.`],
    ['No tests have both values with the current filters.', `Mevcut filtrelerle iki değeri de olan test yok.`], ['No values for the current filters.', `Mevcut filtreler için değer yok.`], ['No tests match these filters.', `Bu filtrelerle eşleşen test yok.`],

    // ---- Fire animation ----
    ['How a droplet fire unfolds', `Bir damlacık yangını nasıl gelişir`],
    ['A single fuel droplet burns from ignition to its recorded ending. Its size and the ending come from the FLEX tests closest to your oxygen and pressure. Gravity changes the flame shape: a sphere with none, a rising plume as it grows.', `Tek bir yakıt damlacığı tutuşmadan kayıtlı sonuna kadar yanar. Boyutu ve sonu, oksijen ve basıncınıza en yakın FLEX testlerinden gelir. Yerçekimi alevin şeklini değiştirir: yerçekimi yokken küre, arttıkça yükselen bir sütun.`],
    ['Scenario', `Senaryo`], ['ISS cabin', `ISS kabini`], ['Moon habitat', `Ay habitatı`], ['Mars habitat', `Mars habitatı`], ['Earth', `Dünya`], ['Earth (reference)', `Dünya (referans)`], ['Moon', `Ay`], ['Mars', `Mars`], ['Microgravity (ISS)', `Mikroyerçekimi (ISS)`], ['Gravity presets', `Yerçekimi ön ayarları`], ['Gravity in g', `g cinsinden yerçekimi`],
    ['Normal air at 1 atm in orbit.', `Yörüngede 1 atm normal hava.`], ['Assumed exploration atmosphere: 34% O₂ at 8.2 psi (0.558 atm). A research scenario, not a final design.', `Varsayılan keşif atmosferi: 8,2 psi'de (0,558 atm) %34 O₂. Bir araştırma senaryosu, nihai tasarım değil.`],
    ['Same assumed exploration atmosphere at Mars gravity.', `Mars yerçekiminde aynı varsayılan keşif atmosferi.`], ['Sea-level air, for comparison.', `Karşılaştırma için deniz seviyesi havası.`],
    ['Ignition', `Tutuşma`], ['Burning', `Yanıyor`], ['Flame out', `Alev söndü`], ['Droplet consumed', `Damlacık tükendi`], ['Droplet breakup', `Damlacık parçalandı`], ['End of test', `Test sonu`],
    ['Illustration', `Çizim`], ['Illustration, shape scaled from buoyancy', `Çizim, şekil kaldırma kuvvetinden ölçeklendi`], ['Animated burning fuel droplet', `Yanan yakıt damlacığı animasyonu`], ['Burn progress', `Yanma ilerlemesi`],
    ['What FLEX measured under these conditions', `Bu koşullarda FLEX ne ölçtü`], ['FLEX ran in microgravity.', `FLEX mikroyerçekiminde çalıştı.`],

    // ---- FLEX analysis ----
    ['What FLEX measured', `FLEX ne ölçtü`],
    ['The 274 burning-droplet tests, filtered by the conditions you choose. Each chart updates with the filters below. Counts are exact; percentages come with a 95% range because some groups are small.', `Seçtiğiniz koşullara göre süzülmüş 274 yanan damlacık testi. Her grafik aşağıdaki filtrelerle güncellenir. Sayılar kesindir; bazı gruplar küçük olduğu için yüzdelerin yanında %95 aralığı verilir.`],
    ['None, nitrogen only', `Yok, yalnızca azot`], ['CO₂ added', `CO₂ eklendi`], ['Helium added', `Helyum eklendi`], ['no diluent', `seyreltici yok`],
    ['How the tests ended, by oxygen level', `Testler nasıl bitti, oksijen düzeyine göre`], ['Each bar is one oxygen band, 4 points wide. Hover a segment for its count and 95% range.', `Her çubuk, 4 puan genişliğinde bir oksijen aralığıdır. Sayısı ve %95 aralığı için bir dilimin üstüne gelin.`],
    ['Size and time', `Boyut ve süre`], ['Each dot is one test. Click a dot to pin it, then open it in the Data page.', `Her nokta bir testtir. Sabitlemek için tıklayın, sonra Veri sayfasında açın.`],
    ['Droplet width at flame-out', `Alev sönerken damlacık genişliği`], ['Droplet width at flame-out (mm)', `Alev sönerken damlacık genişliği (mm)`], ['Burn time (s)', `Yanma süresi (s)`], ['Burning rate (mm²/s)', `Yanma hızı (mm²/s)`],
    ['Too few tests with this measurement to describe a pattern.', `Bir örüntüyü anlatmak için bu ölçümü içeren test çok az.`], ['Open this test in the Data page', `Bu testi Veri sayfasında aç`],
    ['Does adding a diluent change the ending?', `Seyreltici eklemek sonucu değiştiriyor mu?`],
    ['Nitrogen is always present. CO₂ and helium were added in some tests. Only tests that pass the filters above are counted. In the NASA table the column is headed "CO" and the FLEX report lists CO₂ as the added gas.', `Azot her zaman vardır. Bazı testlerde CO₂ ve helyum eklendi. Yalnızca yukarıdaki filtrelerden geçen testler sayılır. NASA tablosunda sütun başlığı "CO" yazıyor, FLEX raporu ise eklenen gazı CO₂ olarak listeliyor.`],
    ['Oxygen band', `Oksijen aralığı`], ['Extinction', `Sönme`], ['Median burn time s', `Ortanca yanma süresi s`], ['Median width at flame-out mm', `Alev sönerken ortanca genişlik mm`], ['oxygen', `oksijen`],
    ['Shares are of the tests in each band. "Few" means under 5 tests. Empty medians mean no test in the band reported that value. Tests that record a flame-out width of 0 mm (8 of them) are left out of the width medians and of the width chart.', `Paylar, her aralıktaki testlere aittir. "Az", 5'ten az test demektir. Boş medyan, aralıktaki hiçbir testin o değeri bildirmediği anlamına gelir. Alev sönme genişliğini 0 mm kaydeden testler (8 tane) genişlik medyanlarının ve genişlik grafiğinin dışında bırakıldı.`],
    ['No tests match these settings.', `Bu ayarlarla eşleşen test yok.`], ['Outcome shares by oxygen band', `Oksijen aralığına göre sonuç payları`], ['Outcome shares by diluent', `Seyrelticiye göre sonuç payları`],

    // ---- Data page ----
    ['Experiment filters', `Deney filtreleri`], ['Fuel, material, test number', `Yakıt, malzeme, test numarası`], ['Oxygen (%)', `Oksijen (%)`], ['Pressure (atm)', `Basınç (atm)`], ['Air flow (cm/s)', `Hava akışı (cm/s)`],
    ['Moving a handle hides rows that have no value for that field.', `Bir tutamacı oynatmak, o alanda değeri olmayan satırları gizler.`], ['Data notes', `Veri notları`], ['Any row', `Herhangi bir satır`], ['No notes', `Not yok`],
    ['Approximate, range or list values', `Yaklaşık, aralık veya liste değerleri`], ['Invalid or non-numeric values', `Geçersiz veya sayısal olmayan değerler`],
    ["Every test row from NASA's 19 combustion experiments, exactly as published, with a note on what each value is: measured, approximate, a range, invalid or not recorded. Nothing is filled in.", `NASA'nın 19 yanma deneyinin her test satırı, yayımlandığı gibi, her değerin ne olduğuna dair bir notla: ölçülmüş, yaklaşık, aralık, geçersiz veya kaydedilmemiş. Hiçbir şey doldurulmadı.`],
    ['Test rows', `Test satırları`], ['Compare tests', `Testleri karşılaştır`], ['Data quality', `Veri kalitesi`], ['Downloads and sources', `İndirmeler ve kaynaklar`],
    ['Experiments at a glance', `Deneylere genel bakış`], ['Safety role', `Güvenlik rolü`], ['All experiments', `Tüm deneyler`],
    ['Click an experiment to filter everything on this page to it. Columns show how many of its rows have each value. "Safety role" is our own grouping of the experiments, not a NASA label.', `Bu sayfadaki her şeyi bir deneye göre süzmek için o deneye tıklayın. Sütunlar, satırlarının kaçında her değerin bulunduğunu gösterir. "Güvenlik rolü", deneylerin bizim kendi gruplamamızdır, bir NASA etiketi değildir.`],
    ['One row is one test, in the order of the NASA table. Click a row to see its raw values, what we did to them, and where they came from. A tilde marks an approximate value, a dash means the value was not recorded, and a dot means the table has no such column at all.', `Bir satır bir testtir, NASA tablosundaki sırayla. Ham değerlerini, onlara ne yaptığımızı ve nereden geldiklerini görmek için bir satıra tıklayın. Yaklaşık işareti yaklaşık bir değeri, tire değerin kaydedilmediğini, nokta ise tabloda böyle bir sütun hiç olmadığını gösterir.`],
    ['Fuel or material', `Yakıt veya malzeme`], ['Pressure atm', `Basınç atm`], ['Air flow cm/s', `Hava akışı cm/s`], ['Burn time s', `Yanma süresi s`],
    ['No fuel or material named', `Yakıt veya malzeme adı yok`], ['Source text', `Kaynak metni`], ['Value used', `Kullanılan değer`], ['How we got it', `Nasıl elde ettik`], ['NASA table column', `NASA tablo sütunu`], ['What we did', `Ne yaptık`],
    ['PSI record', `PSI kaydı`], ['No matching rows. Try widening a range or clearing the search.', `Eşleşen satır yok. Bir aralığı genişletmeyi veya aramayı temizlemeyi deneyin.`],
    ['These tests come from different experiments.', `Bu testler farklı deneylerden geliyor.`], ['They measure different things, so a difference in one column does not mean one test is better or safer than another.', `Farklı şeyler ölçüyorlar; bu yüzden bir sütundaki fark, bir testin diğerinden daha iyi ya da daha güvenli olduğu anlamına gelmez.`],
    ['Same experiment.', `Aynı deney.`], ['Rows marked "differs" show where the test conditions or results changed. Check that fields are measured, not approximate, before reading a small difference.', `"Farklı" işaretli satırlar, test koşullarının veya sonuçlarının nerede değiştiğini gösterir. Küçük bir farkı yorumlamadan önce alanların yaklaşık değil ölçülmüş olduğunu kontrol edin.`],
    ['Tick up to three rows in the table above and they appear here side by side. Values that differ are marked. This lists what the tables say. It does not rank the tests or say which is safer.', `Yukarıdaki tabloda en çok üç satırı işaretleyin, burada yan yana görünürler. Farklı olan değerler işaretlenir. Bu, tabloların söylediğini listeler. Testleri sıralamaz ve hangisinin daha güvenli olduğunu söylemez.`],
    ['For the experiment you selected: how each field breaks down, which rows we could not use, and how we converted units. This is what lets you trust a number or leave it out.', `Seçtiğiniz deney için: her alanın nasıl dağıldığı, hangi satırları kullanamadığımız ve birimleri nasıl dönüştürdüğümüz. Bir sayıya güvenmenizi ya da onu dışarıda bırakmanızı sağlayan budur.`],
    ['Why it is left out', `Neden dışarıda`], ['Values left out', `Dışarıda bırakılan değerler`], ['How we converted units', `Birimleri nasıl dönüştürdük`], ['The source text has no number', `Kaynak metinde sayı yok`],
    ['Oxygen outside 0 to 100%', `Oksijen 0 ile 100% dışında`], ['Pressure of zero or below', `Basınç sıfır veya altında`], ['Negative air speed', `Negatif hava hızı`], ['Not a number in the source', `Kaynakta sayı değil`], ['Showing the first 60.', `İlk 60 gösteriliyor.`],
    ['Take the rows you filtered, or the whole table. Every file below was downloaded from NASA and its SHA-256 fingerprint is recorded so you can check it.', `Süzdüğünüz satırları ya da tablonun tamamını alın. Aşağıdaki her dosya NASA'dan indirildi ve doğrulayabilmeniz için SHA-256 parmak izi kaydedildi.`],
    ['Download filtered rows (CSV)', `Süzülmüş satırları indir (CSV)`], ['Download all rows (CSV)', `Tüm satırları indir (CSV)`], ['Rebuild it yourself', `Kendiniz yeniden üretin`],
    ['Data: NASA Physical Sciences Informatics (PSI), each record licensed CC0 1.0. This page shows what the tables say. It does not rate how safe anything is, and rows from different experiments measure different things and are not directly comparable.', `Veri: NASA Physical Sciences Informatics (PSI), her kayıt CC0 1.0 lisanslı. Bu sayfa tabloların söylediğini gösterir. Hiçbir şeyin ne kadar güvenli olduğunu derecelendirmez; farklı deneylerin satırları farklı şeyler ölçer ve doğrudan karşılaştırılamaz.`],
    ['Data: NASA Physical Sciences Informatics (PSI) experimental tables, public domain (CC0 1.0). FLEX is PSI-69, BASS-II is PSI-25. Every PSI test ran in microgravity on the ISS or a Cygnus vehicle. This tool shows test evidence. It does not rate safety.', `Veri: NASA Physical Sciences Informatics (PSI) deney tabloları, kamu malı (CC0 1.0). FLEX PSI-69, BASS-II PSI-25'tir. Her PSI testi ISS'te veya bir Cygnus aracında mikroyerçekiminde yapıldı. Bu araç test kanıtlarını gösterir. Güvenliği derecelendirmez.`],
    ['x 100 (mole fraction to percent)', `x 100 (mol kesrinden yüzdeye)`], ['as given (percent)', `olduğu gibi (yüzde)`], ['as given (atm)', `olduğu gibi (atm)`], ['as given (cm/s)', `olduğu gibi (cm/s)`], ['as given (seconds)', `olduğu gibi (saniye)`],
    ['divided by 760 (mmHg to atm)', `760'a bölündü (mmHg'den atm'ye)`], ['divided by 1.01325 (bar to atm)', `1,01325'e bölündü (bar'dan atm'ye)`],
    ['No number could be read from the source text', `Kaynak metinden sayı okunamadı`], ['Compare tests', `Testleri karşılaştır`]
  ];
  I.add(T);

  /* ---------- patterns ---------- */
  I.add([
    ['Please ask a NASA combustion research question or clarify the result you mean.', 'NASA yanma araştırmalarıyla ilgili bir soru sorun veya hangi sonucu kastettiğinizi belirtin.'],
    ['This question could not be linked to the supported NASA combustion experiments. An active page or FLEX condition is not evidence that the question is relevant. Please name the experiment, material, measurement or result you want explained. No prediction, source citation or LLM answer was generated.', 'Bu soru desteklenen NASA yanma deneyleriyle ilişkilendirilemedi. Sayfanın veya FLEX koşulunun seçili olması, sorunun konuyla ilgili olduğunu göstermez. Açıklanmasını istediğiniz deneyi, malzemeyi, ölçümü veya sonucu belirtin. Tahmin, kaynak atfı veya LLM yanıtı üretilmedi.'],
    ['Ask about NASA material tests, flame behavior, smoke detection or the active FLEX estimate.', 'NASA malzeme deneyleri, alev davranışı, duman algılama veya aktif FLEX tahmini hakkında soru sorabilirsiniz.'],
    // page 'Material lab'
    ['Within {} point', `{1} puan içinde`], ['Within {} points', `{1} puan içinde`], ['{} points', `{1} puan`], ['{} point', `{1} puan`],
    ['Your setting, {} oxygen, is marked on every chart.', `Ayarınız, {1} oksijen, her grafikte işaretli.`],
    ['The highest tested level is {}. Everything below is the nearest evidence, not evidence for your setting.', `Test edilen en yüksek düzey {1}. Aşağıdakilerin hepsi en yakın kanıttır, sizin ayarınız için kanıt değildir.`],
    ['{} tests had CO above the sensor limit and are left out of CO charts.', `{1} testte CO sensör sınırının üstündeydi ve CO grafiklerinin dışında bırakıldı.`],
    ['{} test had CO above the sensor limit and is left out of CO charts.', `{1} testte CO sensör sınırının üstündeydi ve CO grafiklerinin dışında bırakıldı.`],
    ['of {} rows shown', `/ {1} satır gösteriliyor`], ['of {} tests', `/ {1} test`],
    ['{} tests, tested {} to {}% oxygen', `{1} test, %{2} ile %{3} oksijen arasında test edildi`], ['{} test, tested {} to {}% oxygen', `{1} test, %{2} ile %{3} oksijen arasında test edildi`],
    ['{} tests, tested at {}% oxygen', `{1} test, %{2} oksijende test edildi`], ['{} test, tested at {}% oxygen', `{1} test, %{2} oksijende test edildi`],
    ['median {}, {} tests', `ortanca {1}, {2} test`], ['median {}, {} test', `ortanca {1}, {2} test`], ['{} nearby, no {} reading', `{1} yakında, {2} ölçümü yok`],
    ['No test within {} points', `{1} puan içinde test yok`], ['No test within {} point', `{1} puan içinde test yok`], ['Nearest is {} points away', `En yakını {1} puan uzakta`], ['Nearest is {} point away', `En yakını {1} puan uzakta`],
    ['No {} readings', `{1} ölçümü yok`], ['{} tests', `{1} test`], ['{} test', `{1} test`], ['tests {} and {}', `testler {1} ve {2}`],
    ['{}% chosen', `%{1} seçildi`], ['Restriction {}', `Kısıtlama {1}`],
    ['over {} tests: {}. Tests differ in sample shape and size, so this describes the data and does not show a cause.', `{1} testte: {2}. Testler numune şekli ve boyutu bakımından farklıdır; bu yüzden bu veriyi anlatır, bir neden göstermez.`],
    ['over {} tests: {}. Fuel, diluent and pressure also vary between tests, so this describes the data and does not show a cause.', `{1} testte: {2}. Yakıt, seyreltici ve basınç da testler arasında değişir; bu yüzden bu veriyi anlatır, bir neden göstermez.`],
    ['{#} very strong positive', `{1} çok güçlü pozitif`], ['{#} very strong negative', `{1} çok güçlü negatif`], ['{#} strong positive', `{1} güçlü pozitif`], ['{#} strong negative', `{1} güçlü negatif`],
    ['{#} moderate positive', `{1} orta düzeyde pozitif`], ['{#} moderate negative', `{1} orta düzeyde negatif`], ['{#} weak positive', `{1} zayıf pozitif`], ['{#} weak negative', `{1} zayıf negatif`], ['{#} very weak', `{1} çok zayıf`],
    ['{}: median {}, middle half {} to {}, range {} to {}, {} tests', `{1}: medyan {2}, orta yarı {3} ile {4} arası, aralık {5} ile {6}, {7} test`],
    ['{}, oxygen {} to {}%: median {}, middle half {} to {}, {} tests (too few to trust)', `{1}, oksijen %{2} ile %{3}: medyan {4}, orta yarı {5} ile {6} arası, {7} test (güvenmek için çok az)`],
    ['{}, oxygen {} to {}%: median {}, middle half {} to {}, {} tests', `{1}, oksijen %{2} ile %{3}: medyan {4}, orta yarı {5} ile {6} arası, {7} test`],
    ['{}, {}: median {} over {} tests', `{1}, {2}: medyan {3}, {4} test üzerinden`], ['{}, oxygen {} to {}%: {} tests', `{1}, oksijen %{2} ile %{3}: {4} test`], ['{}, oxygen {} to {}%: {} test', `{1}, oksijen %{2} ile %{3}: {4} test`],
    ['Oxygen {} to {}%', `Oksijen %{1} ile %{2}`], ['Oxygen {} to {}%', `Oksijen %{1} ile %{2}`],
    ['{} status breakdown for all experiments', `{1} durum dağılımı, tüm deneyler`], ['{} status breakdown for {}', `{2} için {1} durum dağılımı`],
    ['{} against {}', `{2} ile {1}`], ['{} by group', `Gruba göre {1}`], ['{} by oxygen band', `Oksijen aralığına göre {1}`], ['Median {} in two oxygen ranges', `İki oksijen aralığında ortanca {1}`],
    // sentences made of pieces (single nodes)
    ['Oxygen {}.', `Oksijen {1}.`], ['No oxygen level recorded.', `Oksijen düzeyi kaydı yok.`], ['CO change {} ppm.', `CO değişimi {1} ppm.`], ['CO above sensor limit.', `CO sensör sınırının üstünde.`],
    ['Oxygen change {} vol%.', `Oksijen değişimi {1} hacim %.`], ['Investigator {}.', `Araştırmacı {1}.`], ['Source: NASA PSI {}.', `Kaynak: NASA PSI {1}.`],

    // sliders
    ['Up to {}', `En çok {1}`], ['{} and above', `{1} ve üzeri`], ['{#} to {#} %', `{1} – {2} %`], ['{#} to {#}%', `%{1} – %{2}`], ['{#} to {#}', `{1} – {2}`],
    ['{#}, {#} and {#}', `{1}, {2} ve {3}`], ['All experiments ({} rows)', `Tüm deneyler ({1} satır)`], ['{} ({})', `{1} ({2})`],
    ['{}, {#} to {#}%', `{1}, %{2} – %{3}`], ['{}, no diluent', `{1}, seyreltici yok`], ['{}, CO₂ added', `{1}, CO₂ eklendi`], ['{}, Helium added', `{1}, helyum eklendi`],

    // fire page
    ['{} s of about {} s, droplet {} mm wide', `{1} s / yaklaşık {2} s, damlacık {3} mm genişliğinde`],
    ['Matched on {} droplets within {} points of {}% oxygen and {} atm of {} atm.', `{1} damlacıkları, %{3} oksijene {2} puan ve {5} atm basınca {4} atm yakınlıkta eşleştirildi.`],
    ['No close match for {}% oxygen at {} atm, so this shows all {} {} tests, {} to {}% oxygen.', `%{1} oksijen ve {2} atm için yakın eşleşme yok; bu yüzden tüm {3} {4} testi gösteriliyor, oksijen %{5} ile %{6} arası.`],
    [' No table here was measured at {} g. The droplet history and ending come from the data. The flame shape at this gravity is scaled from buoyancy and is not measured.', `Buradaki hiçbir tablo {1} g'de ölçülmedi. Damlacığın gidişatı ve sonu veriden gelir. Bu yerçekimindeki alev şekli kaldırma kuvvetinden ölçeklenmiştir ve ölçülmemiştir.`],
    ['No table here was measured at {} g. The droplet history and ending come from the data. The flame shape at this gravity is scaled from buoyancy and is not measured.', `Buradaki hiçbir tablo {1} g'de ölçülmedi. Damlacığın gidişatı ve sonu veriden gelir. Bu yerçekimindeki alev şekli kaldırma kuvvetinden ölçeklenmiştir ve ölçülmemiştir.`],
    ['{#}% of {#} tests (95% range {#}% to {#}%)', `%{1}, {2} testten (%95 aralığı: %{3} – %{4})`],
    ['ended in extinction (95% range {#}% to {#}%)', `sönmeyle bitti (%95 aralığı: %{1} – %{2})`], ['ended in disruption (95% range {#}% to {#}%)', `parçalanmayla bitti (%95 aralığı: %{1} – %{2})`], ['ended in completion (95% range {#}% to {#}%)', `tamamlanmayla bitti (%95 aralığı: %{1} – %{2})`],
    ['{}, Extinction: {#} of {#} tests ({#}%, 95% range {#} to {#}%)', `{1}, Sönme: {3} testten {2} ({4}%, %95 aralığı {5} – {6}%)`],
    ['{}: {#} of {#} tests ({#}%, 95% range {#} to {#}%)', `{1}: {3} testten {2} ({4}%, %95 aralığı {5} – {6}%)`], ['{}: {#} of {#} rows', `{1}: {3} satırdan {2}`], ['{}: {#} of {#} tests', `{1}: {3} testten {2}`],

    // data page
    ['Showing {} of {} rows. {} selected to compare,', `{2} satırdan {1} tanesi gösteriliyor. {3} satır karşılaştırma için seçildi,`], ['Showing {} of {} rows.', `{2} satırdan {1} tanesi gösteriliyor.`],
    ['Showing {} of {} tests. Empty cells were not measured.', `{2} testten {1} tanesi gösteriliyor. Boş hücreler ölçülmedi.`], ['Show all {}', `Tümünü göster ({1})`],
    ['row {}', `satır {1}`], ['Row {} of', `Satır {1},`], ['Row {} of {}', `Satır {1}, {2}`], ['NASA PSI record {}', `NASA PSI kaydı {1}`], ['License {}', `Lisans {1}`], ['Cite {}', `{1} alıntısı`],
    ['Compare {}', `{1} testini karşılaştır`], ['Remove one to add another (up to {})', `Birini çıkarın, başkasını ekleyin (en çok {1})`],
    ['This table has no {} column', `Bu tabloda {1} sütunu yok`], ['Nothing selected yet. Tick the Compare box on up to {} rows.', `Henüz bir şey seçilmedi. En çok {1} satırda Karşılaştır kutusunu işaretleyin.`],
    ['Values left out ({})', `Dışarıda bırakılan değerler ({1})`], ['No invalid or non-numeric values for {}.', `{1} için geçersiz veya sayısal olmayan değer yok.`],
    ['Source text: {}. Oxygen outside 0 to 100%, so it is left out.', `Kaynak metni: {1}. Oksijen 0 ile 100% dışında, bu yüzden dışarıda bırakıldı.`], ['Source text: {}. Pressure of zero or below, so it is left out.', `Kaynak metni: {1}. Basınç sıfır veya altında, bu yüzden dışarıda bırakıldı.`],
    ['Source text: {}. Negative air speed, so it is left out.', `Kaynak metni: {1}. Negatif hava hızı, bu yüzden dışarıda bırakıldı.`], ['Source text: {}. Not a number in the source, so it is left out.', `Kaynak metni: {1}. Kaynakta sayı değil, bu yüzden dışarıda bırakıldı.`], ['Source text: {}', `Kaynak metni: {1}`],
    ['{}, x 100 (mole fraction to percent)', `{1}, x 100 (mol kesrinden yüzdeye)`], ['{}, as given (percent)', `{1}, olduğu gibi (yüzde)`], ['{}, as given (atm)', `{1}, olduğu gibi (atm)`], ['{}, as given (cm/s)', `{1}, olduğu gibi (cm/s)`], ['{}, as given (seconds)', `{1}, olduğu gibi (saniye)`],
    ['{}, divided by 760 (mmHg to atm)', `{1}, 760'a bölündü (mmHg'den atm'ye)`], ['{}, divided by 1.01325 (bar to atm)', `{1}, 1,01325'e bölündü (bar'dan atm'ye)`],
    ['Spread between highest and lowest, for fields where every test has one measured number: {}.', `En yüksek ile en düşük arasındaki fark, her testte tek bir ölçülmüş sayı bulunan alanlar için: {1}.`],
    ['{#} of {#}', `{1} / {2}`],
    ['{#} of {#} rows', `{2} satırdan {1}`],
    ['{#} groups have at least {#} tests in both ranges, so only those differences are worth reading.', `{1} grubun iki aralıkta da en az {2} testi var; bu yüzden yalnızca bu farkların okunmaya değer.`],
    ['{#} group has at least {#} tests in both ranges, so only that difference is worth reading.', `{1} grubun iki aralıkta da en az {2} testi var; bu yüzden yalnızca bu farkın okunmaya değer.`],
    ['All values in {}. "Few" means under 5 tests. The last column is a rank correlation with starting oxygen, within that group only.', `Tüm değerler {1} cinsinden. "Az", 5'ten az test demektir. Son sütun, yalnızca o grup içinde başlangıç oksijeniyle sıra korelasyonudur.`],
    ['Extinction {#}%', `Sönme %{1}`], ['Disruption {#}%', `Parçalanma %{1}`], ['Completion {#}%', `Tamamlanma %{1}`],
    ['Compare FLEX tests {#}, {#} and {#}.', `FLEX {1}, {2} ve {3} numaralı testleri karşılaştır.`],
    ['{} tests along the oxygen axis', `{1} testlerinin oksijen ekseni üzerindeki yeri`], ['{}, highest', `{1}, en yüksek`], ['{}, lowest', `{1}, en düşük`]
  ]);
  I.add([
    ['Number of tests by group and oxygen band', `Gruba ve oksijen aralığına göre test sayısı`], ['Oxygen axis', `Oksijen ekseni`],
    ['First oxygen range (%), highest', `Birinci oksijen aralığı (%), en yüksek`], ['First oxygen range (%), lowest', `Birinci oksijen aralığı (%), en düşük`],
    ['Second oxygen range (%), highest', `İkinci oksijen aralığı (%), en yüksek`], ['Second oxygen range (%), lowest', `İkinci oksijen aralığı (%), en düşük`],
    ['rod', `çubuk`], ['film', `film`], ['slab', `levha`], ['sphere', `küre`], ['candle', `mum`]
  ]);

  // sort-arrow variants of the table headers
  ['Oxygen %', 'Oxygen change', 'CO₂ change', 'CO change ppm', 'Source', 'Test', 'Material', 'Shape', 'Investigator', 'Airflow restriction', 'Experiment', 'Fuel or material', 'Pressure atm', 'Air flow cm/s', 'Burn time s', 'Outcome'].forEach(function (h) {
    ['▲', '▼'].forEach(function (a) { var t = I.tr(h); I.add([[h + ' ' + a, t + ' ' + a]]); });
  });

  /* ---------- status breakdown lines: "12 measured, 3 invalid, ..." ---------- */
  var STATUS = { 'measured': `ölçüldü`, 'approximate': `yaklaşık`, 'range or list': `aralık veya liste`, 'invalid': `geçersiz`, 'no number in source': `kaynakta sayı yok`, 'not recorded': `kaydedilmedi`, 'not in this table': `bu tabloda yok` };
  I.custom(function (s) {
    if (!/^\d+ [a-z]/.test(s)) return null;
    var parts = s.split(', '), out = [];
    for (var i = 0; i < parts.length; i++) {
      var m = /^(\d+) (.+)$/.exec(parts[i]);
      if (!m || !STATUS[m[2]]) return null;
      out.push(m[1] + ' ' + STATUS[m[2]]);
    }
    return out.join(', ');
  });

  /* ---------- hover text built from small pieces ---------- */
  I.fragments([
    [/, ended in extinction/g, `, sönmeyle bitti`], [/, ended in disruption/g, `, parçalanmayla bitti`], [/, ended in completion/g, `, tamamlanmayla bitti`],
    [/, with CO₂/g, `, CO₂ eklenmiş`], [/, with Helium/g, `, helyum eklenmiş`], [/oxygen (?=[\d~])/g, `oksijen `],
    ['; droplet width when the flame went out ', `; alev sönerken damlacık genişliği `], ['; burn time ', `; yanma süresi `], ['; burning rate ', `; yanma hızı `],
    ['; oxygen ', `; oksijen `], ['; CO over range', `; CO ölçüm sınırının üstünde`], [/\(Starting oxygen /g, `(başlangıç oksijeni `], [/\(Oxygen change /g, `(oksijen değişimi `], [/\(CO₂ change /g, `(CO₂ değişimi `], [/\(CO change /g, `(CO değişimi `],
    [/, Oxygen change /g, `, oksijen değişimi `], [/, CO₂ change /g, `, CO₂ değişimi `], [/, CO change /g, `, CO değişimi `], [/, Starting oxygen /g, `, başlangıç oksijeni `], [/, burn time /g, `, yanma süresi `]
  ]);
})();

/* ---------- Saffire case study: story layout (case-saffire.html / case-saffire.js) ---------- */
(function () {
  'use strict';
  var I = FF.i18n;
  I.add([
    // hero
    ['Case study · NASA Saffire experiments · 2020–2023', `Vaka incelemesi · NASA Saffire deneyleri · 2020–2023`],
    ['What did the fire do to the air?', `Yangın havaya ne yaptı?`],
    ['After a cargo ship leaves the International Space Station, NASA lit real fires inside it on purpose — with nobody on board — before it burned up in the atmosphere.',
      `Bir kargo aracı Uluslararası Uzay İstasyonu'ndan ayrıldıktan sonra NASA, araç atmosferde yanıp yok olmadan önce içinde bilerek gerçek yangınlar başlattı. Araçta kimse yoktu.`],
    ['We follow one of those fires,', `Bu yangınlardan birini,`],
    [', from ignition to the selected smoke criterion, alongside the reported changes in the air.',
      `'ü izliyoruz: ateşlemeden seçili duman ölçütüne kadar geçen süreyi ve havanın değişimini.`],
    ['▶ Watch the fire unfold', `▶ Yangını izle`],
    ['Skip to the key finding', `Ana bulguya geç`],
    ['Illustration · not to scale', `Temsili çizim · ölçekli değil`],
    // setup
    ['An empty spacecraft', `Boş bir uzay aracı`],
    ['A Cygnus cargo ship, far from the station. Free air inside:', `İstasyondan uzaktaki bir Cygnus kargo aracı. İçerideki serbest hava:`],
    ['— about one small bedroom.', `— yaklaşık küçük bir yatak odası kadar.`],
    ['One sheet of plastic', `Tek bir plastik levha`],
    ['A 1 cm-thick sheet of acrylic (PMMA, the clear plastic of display cases), lit by a hot wire.',
      `1 cm kalınlığında akrilik levha (PMMA, vitrinlerdeki şeffaf plastik), sıcak bir telle tutuşturuldu.`],
    ['Thin, oxygen-rich air', `Seyrek, oksijeni bol hava`],
    ['(about half of sea-level pressure) with', `(deniz seviyesi basıncının yaklaşık yarısı) ve`],
    ['oxygen — Earth air has 21 %. NASA calls this an exploration atmosphere.', `oksijen; Dünya havasında bu oran %21. NASA buna keşif atmosferi diyor.`],
    // story
    ['Step 1 · Watch it happen', `Adım 1 · Olayı izleyin`],
    ['Twenty-four minutes inside an empty spacecraft', `Boş bir uzay aracında yirmi dört dakika`],
    ['Press play. The clock runs through the published events of Saffire VI-3 — the clock is illustrative between event markers.',
      `Oynat'a basın. Saat, Saffire VI-3'ün yayımlanmış olaylarını sırayla gösterir; olay işaretleri arasındaki saat temsili olarak ilerler.`],
    ['Experiment clock', `Deney saati`],
    ['Elapsed since ignition, capped at the criterion', `Ateşlemeden itibaren geçen süre`],
    ['Play', `Oynat`], ['Pause', `Duraklat`], ['Play from start', `Baştan oynat`], ['Show all', `Tümünü göster`],
    ['ignition to flow stop', `ateşlemeden akışın durmasına`],
    ['Reported burn duration: {#} s', `Bildirilen yanma süresi: {1} sn`],
    ['{#} min', `{1} dk`],
    ['Fan on', `Fan açık`], ['Ignition', `Tutuşma`], ['Smoke hits the selected smoke criterion', `Duman seçili duman ölçütünde`],
    ['Breeze turned down', `Akış azaltıldı`], ['Fan off, test over', `Fan kapandı, deney bitti`],
    ['{} · Fan on', `{1} · Fan açık`], ['{} · Ignition', `{1} · Tutuşma`], ['{} · Smoke hits the selected smoke criterion', `{1} · Duman seçili duman ölçütünde`],
    ['{} · Breeze turned down', `{1} · Akış azaltıldı`], ['{} · Fan off, test over', `{1} · Fan kapandı, deney bitti`],
    ['A gentle breeze (20 cm/s) flows over the sample. Nothing is burning yet.', `Numunenin üzerinden hafif bir hava akışı (20 cm/s) geçiyor. Henüz hiçbir şey yanmıyor.`],
    ['A hot wire lights the plastic. The fire starts — and the smoke starts to build.', `Sıcak tel plastiği tutuşturuyor. Yangın başlıyor ve duman birikmeye başlıyor.`],
    ['Smoke near the sensor crosses 1 mg/m³, the smoke-concentration criterion selected by the authors. By now, much of the harmful gas is already out.',
      `Sensörün yanındaki duman, yazarların seçtiği duman konsantrasyonu ölçütü olan 1 mg/m³'ü geçiyor. Bu ana kadar zararlı gazın büyük kısmı zaten salınmış durumda.`],
    ['Air flow drops from 20 to 5 cm/s. With less fresh air mixing in, CO and CO₂ at the outlet climb.', `Hava akışı 20'den 5 cm/s'ye düşüyor. Daha az temiz hava karıştığı için çıkıştaki CO ve CO₂ yükseliyor.`],
    ['The fan stops. Saffire VI-3 is complete.', `Fan duruyor. Saffire VI-3 tamamlandı.`],
    ['Event {#} of {#}', `Olay {1} / {2}`],
    ['Press play, or tap any event on the line.', `Oynat'a basın ya da çizgideki bir olaya dokunun.`],
    // finding
    ['Step 2 · The key finding', `Adım 2 · Ana bulgu`],
    ['Elapsed from ignition: {#} min {#} s to the selected smoke criterion.', `Ateşlemeden seçili duman ölçütüne: {1} dk {2} sn.`],
    ['And by the time it did, the authors note, much of the harmful gas had already been released.', `Yazarlara göre o ana kadar zararlı gazın büyük kısmı zaten salınmıştı.`],
    ['Ignition to selected smoke criterion', `Ateşlemeden seçili duman ölçütüne`],
    ['{#} min {#} s · from ignition ({#} s) to the 1 mg/m³ line ({#} s)', `{1} dk {2} sn · tutuşmadan ({3} s) 1 mg/m³ çizgisine ({4} s) kadar`],
    ['Computed by us: {#} − {#}', `Bizim hesabımız: {1} − {2}`],
    ['Rise in CO₂', `CO₂ artışı`], ['Rise in carbon monoxide (CO)', `Karbon monoksit (CO) artışı`], ['Rise in CO', `CO artışı`],
    ['Above the 1-hour limit the authors compared it with.', `Yazarların karşılaştırdığı 1 saatlik sınırın üzerinde.`],
    ['About {#}× the 24-hour limit, still below the 1-hour limit.', `24 saatlik sınırın yaklaşık {1} katı; 1 saatlik sınırın ise altında.`],
    ['Reported · NTRS 20240002981 Table 2', `Raporlanan · NTRS 20240002981 Tablo 2`], ['Reported · JSC 20584 limits', `Raporlanan · JSC 20584 sınırları`],
    ['NASA 1-h limit {#}', `NASA 1 sa sınırı {1}`], ['24-h {#}', `24 sa {1}`], ['1-h {#}', `1 sa {1}`],
    ['24-h limit {#}', `24 sa sınırı {1}`], ['1-h limit {#}', `1 sa sınırı {1}`],
    ['Gas values are', `Gaz değerleri, boş bir uzay aracında tek bir sensörün yanında ölçülen`],
    ['increases', `artışlardır`],
    ['measured near one sensor in an empty spacecraft, compared by the NASA authors with crew limits. They are not what a person would have breathed.',
      `ve NASA yazarları tarafından mürettebat sınırlarıyla karşılaştırılmıştır. Bir insanın soluyacağı havayı göstermezler.`],
    // thin vs thick
    ['Step 3 · Not every fire is the same', `Adım 3 · Her yangın aynı değil`],
    ['Fabric and PMMA results in these tests', `Bu deneylerde kumaş ve PMMA sonuçları`],
    ['Five tests have gas results; materials and test conditions differ.', `Beş deneyin gaz sonuçları var; malzemeler ve deney koşulları farklı.`],
    ['Thin fabric', `İnce kumaş`], ['Thick plastic', `Kalın plastik`], ['Thick plastic (PMMA)', `Kalın plastik (PMMA)`], ['Not published', `Yayımlanmamış`],
    ['Cotton / SIBAL cloth · {}', `Pamuk / SIBAL kumaş · {1}`], ['Acrylic (PMMA) · {}', `Akrilik (PMMA) · {1}`],
    ['Burned for', `Yanma süresi`], ['CO rise', `CO artışı`], ['CO₂ rise', `CO₂ artışı`],
    ['not published (gap, not zero)', `yayımlanmadı (boşluk, sıfır değil)`],
    ['SIBAL cloth', `SIBAL kumaş`], ['Cotton', `Pamuk`], ['PMMA 1-sided', `PMMA tek yüz`], ['PMMA 2-sided', `PMMA çift yüz`], ['PMMA ribbed', `PMMA nervürlü`],
    // why
    ['Step 4 · Why this matters', `Adım 4 · Bu neden önemli`],
    ['Catching smoke in space is harder than it sounds.', `Uzayda dumanı yakalamak sanıldığından zor.`],
    ['The smoke is tiny', `Duman çok küçük`],
    ['In Saffire IV–V, most of the smoke mass was in particles smaller than 1 micrometre (PM1) — dozens of times thinner than a human hair.',
      `Saffire IV–V'te duman kütlesinin çoğu 1 mikrometreden küçük parçacıklardaydı (PM1); bir insan saç telinden onlarca kat ince.`],
    ['No detector sees everything', `Hiçbir dedektör her şeyi görmüyor`],
    ['On the space station, the light-based smoke detector often missed the small particles from Teflon and Kapton — materials common in electronics.',
      `Uzay istasyonunda ışık tabanlı duman dedektörü, elektronikte yaygın olan Teflon ve Kapton'un küçük parçacıklarını çoğu zaman kaçırdı.`],
    ['The open question', `Açık soru`],
    ['Could watching CO and CO₂ give an earlier warning than smoke alone? These results raise that question. They do not answer it.',
      `CO ve CO₂'yi izlemek yalnızca dumana bakmaktan daha erken uyarı verebilir mi? Bu sonuçlar soruyu ortaya koyuyor ama cevaplamıyor.`],
    ['Our reading — not a NASA conclusion', `Bizim yorumumuz, NASA'nın vardığı bir sonuç değil`],
    // limits
    ['Step 5 · What this does not tell us', `Adım 5 · Bunun bize söylemedikleri`],
    ["We say what we don't know.", `Bilmediğimizi söylüyoruz.`],
    ['No crew was on board.', `Araçta mürettebat yoktu.`], ['This is not a crew-exposure or survival assessment.', `Bu bir mürettebat maruziyeti ya da hayatta kalma değerlendirmesi değil.`],
    ['Increases near one sensor.', `Tek bir sensörün yanındaki artışlar.`], ['Not the full air a person would breathe in a cabin.', `Kabinde bir insanın soluyacağı havanın tamamı değil.`],
    ['V-3 and V-4 have no published gas data.', `V-3 ve V-4'ün yayımlanmış gaz verisi yok.`], ['We show them as gaps, never as zero.', `Bunları sıfır olarak değil, boşluk olarak gösteriyoruz.`],
    ['Microgravity is not the Moon or Mars.', `Mikro yerçekimi Ay ya da Mars değildir.`], ['These results are not carried over to partial gravity.', `Bu sonuçlar kısmi yerçekimine taşınmıyor.`],
    // ask
    ['Ask the case', `Vakaya sor`],
    ['Answers come only from the published Saffire, SAME and Fortenberry sources, with citations.', `Cevaplar yalnızca yayımlanmış Saffire, SAME ve Fortenberry kaynaklarından, atıflarıyla birlikte gelir.`],
    ['When did smoke reach the selected smoke criterion?', `Duman seçili duman ölçütüne ne zaman ulaştı?`],
    ['How do CO and CO₂ compare to NASA limits?', `CO ve CO₂ NASA sınırlarıyla nasıl karşılaştırılıyor?`],
    ['Fabric vs plastic: which released more gas?', `Kumaş mı plastik mi: hangisi daha çok gaz saldı?`],
    ['Why are smoke particles hard to detect?', `Duman parçacıkları neden zor algılanıyor?`],
    ['Why are V-3 and V-4 blank?', `V-3 ve V-4 neden boş?`],
    // expert
    ['For researchers', `Araştırmacılar için`],
    ['Full data, sources and audit trail', `Tüm veriler, kaynaklar ve denetim izi`],
    ['Every number above traces back to a NASA report page or slide. Open a panel to check it.', `Yukarıdaki her sayı bir NASA rapor sayfasına ya da slaytına dayanıyor. Kontrol etmek için bir paneli açın.`],
    ['All 7 tests: conditions and flow schedule', `7 testin tümü: koşullar ve akış programı`],
    ['Reported + derived pO₂', `Raporlanan + türetilmiş pO₂`],
    ['Full measurement table (heat, temperature, CO₂, CO)', `Tam ölçüm tablosu (ısı, sıcaklık, CO₂, CO)`],
    ['NTRS 20240002981 Table 2', `NTRS 20240002981 Tablo 2`],
    ['Timeline sources and the derived 344 s', `Zaman çizelgesi kaynakları ve türetilmiş 344 s`],
    ['Derived: 981 − 637', `Türetilmiş: 981 − 637`],
    ['Evidence limits and unresolved source notes', `Kanıt sınırları ve çözülmemiş kaynak notları`],
    ['Audit 2026-11-14', `Denetim 2026-11-14`],
    ['Related detection research (SAME & Fortenberry)', `İlgili algılama araştırmaları (SAME ve Fortenberry)`],
    ['Separate studies', `Ayrı çalışmalar`],
    ['Source ledger, coverage and export', `Kaynak defteri, kapsam ve dışa aktarma`],
    ['SHA-256 provenance', `SHA-256 kaynak izi`],
    ['Focus test', `Odak test`], ['Flight', `Uçuş`], ['Fuel group', `Yakıt grubu`], ['Reset to VI-3', `VI-3'e dön`],
    ['Exports keep null values, derived tags, SHA-256 provenance and the non-certification limits.', `Dışa aktarımlar boş değerleri, türetilmiş etiketleri, SHA-256 kaynak izini ve sertifika olmadığı uyarısını korur.`],
    ['Saffire IV–VI case study · descriptive presentation of published NASA / NIST findings only · kept separate from the core PSI-25 / PSI-69 tables. ·',
      `Saffire IV–VI vaka incelemesi · yalnızca yayımlanmış NASA / NIST bulgularının betimleyici sunumu · çekirdek PSI-25 / PSI-69 tablolarından ayrı tutulur. ·`],
    ['How AI & numerical checks work', `Yapay zekâ ve sayısal kontroller nasıl çalışır`],
    ['Team GeNAIus, NASA Space Apps Challenge 2026.', `GeNAIus Ekibi, NASA Space Apps Challenge 2026.`]
  ]);
})();
