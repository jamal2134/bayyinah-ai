# التوثيق التقني لمشروع بيّنة
## Bayyinah AI Technical Documentation

**اسم المشروع:** بيّنة | Bayyinah AI  
**نوع المشروع:** منصة ذكية مساعدة للتحقق من المحتوى الإسلامي  
**نطاق الوثيقة:** المعمارية، مسار التحقق، المصادر، التشغيل، الاختبارات، النشر، والقيود الحالية

## 1. التعريف بالمشروع

بيّنة نظام تحقق مدعوم بالذكاء الاصطناعي وقابل للتتبع. يحوّل النص إلى مطالبات مستقلة قابلة للتحقق، ويصنف كل مطالبة، ويوجهها إلى المصدر المعرفي المتخصص، ويسترجع أدلة مرشحة، ثم يتحقق من ارتباط كل دليل بالسجل الصحيح ومن السمات المطلوبة. بعد ذلك يحفظ حالات الدعم والتعارض وعدم الحسم، ويطبق قواعد حتمية لإنتاج نتيجة موثقة مرتبطة بمصادرها.

هدف المشروع هو الانتقال من معلومة تبدو صحيحة إلى نتيجة يمكن فحص أدلتها وتتبع مسارها. وهو موجّه إلى:

- لجان التحكيم التي تحتاج إلى فهم المشكلة والابتكار وموثوقية المنتج.
- المطورين الذين يريدون تشغيل النظام وفهم مكوناته.
- المراجعين التقنيين الذين يريدون معرفة مواضع استخدام الذكاء الاصطناعي ومواضع إنفاذ القواعد البرمجية.
- الباحثين والمستخدمين الذين يحتاجون إلى أداة مساعدة، مع بقاء الحكم العلمي النهائي لأهل الاختصاص.

### المبادئ الأساسية

**Similarity ≠ Evidence — التشابه لا يساوي دليلًا:** العثور على نص قريب لغويًا لا يثبت أنه الآية أو الحديث أو السجل المقصود.

**Retrieval ≠ Verification — الاسترجاع لا يساوي تحققًا:** نتيجة البحث تصبح `EvidenceCandidate` فقط، ولا تؤثر في القرار قبل المحاذاة والتحقق من السمات.

**AI proposes. Code enforces. — الذكاء الاصطناعي يقترح، والكود يفرض القواعد:** يستخدم Claude في الاستخراج المنظم وبعض المقارنات الدلالية المغلقة على الأدلة، لكن النموذج لا يملك صلاحية إصدار القرار النهائي مباشرة. محرك برمجي حتمي يطبق ترتيب القواعد ويصدر الحالة النهائية.

## 2. المشكلة

التحقق من المحتوى الإسلامي ليس مجرد `Search` أو مسار `RAG` بسيط. قد يجمع النص الواحد مطالبات عن القرآن، والحديث، وشرح الحديث، والتفسير، والفقه، والعقيدة، والسيرة، والتاريخ الإسلامي. ولكل مجال مصادر وبنية سجل وسمات مختلفة.

من أمثلة الإشكالات التي يعالجها النظام:

- قد يكون نص الآية صحيحًا، لكن اسم السورة أو رقم الآية خاطئًا.
- قد يكون متن الحديث صحيحًا، لكن الراوي المنسوب إليه أو المصدر غير صحيح.
- قد تظهر نتيجة مشابهة لغويًا، لكنها تنتمي إلى سجل آخر.
- قد تدعم الأدلة بعض سمات المطالبة ولا تدعم سمات أخرى.
- عدم العثور على دليل، أو تعذر مزود خارجي، لا يثبت خطأ المعلومة.
- وجود حكمين منسوبين إلى عالمين أو طريقين مختلفين يحتاج إلى حفظ النسبة والسياق، لا إلى دمجهما آليًا.

## 3. فكرة الحل

```text
النص المدخل
    ↓
استخراج المطالبات — Claim Extraction
    ↓
تصنيف المطالبات — Claim Classification
    ↓
التوجيه للمصدر — Source Routing
    ↓
استرجاع الأدلة المرشحة — Evidence Retrieval
    ↓
محاذاة السجل — Record Alignment
    ↓
التحقق من السمات — Attribute Validation
    ↓
كشف التعارض — Conflict Detection
    ↓
محرك القرار الحتمي — Deterministic Decision Engine
    ↓
تقرير موثق وقابل للتتبع — Traceable Report
```

1. **استخراج المطالبات:** يحلل Claude النص ويقترح مطالبات مستقلة وسماتها واستعلاماتها، ثم تتحقق نماذج Pydantic الصارمة من البنية.
2. **التصنيف:** تُسند إلى كل مطالبة قيم مضبوطة مثل `domain` و`claim_type` و`attributes`.
3. **التوجيه:** يقرأ كود حتمي التصنيف والسمات ويُنشئ `RetrievalPlan` للمزود أو المزودين المناسبين.
4. **الاسترجاع:** تنفذ adapters استعلامات محدودة العدد وتحوّل النتائج إلى `EvidenceCandidate` موحد.
5. **محاذاة السجل:** يتحقق النظام من أن الدليل يخص الآية أو الحديث أو السياق المقصود، لا مجرد موضوع مشابه.
6. **التحقق من السمات:** تُفحص سمات مثل النص، والسورة، والآية، والراوي، والمصدر، والحكم، والتاريخ كلٌّ على حدة.
7. **كشف التعارض:** تُحفظ معرفات الأدلة الداعمة والمناقضة، ولا يُخفى التعارض الحقيقي.
8. **القرار:** يجمع محرك حتمي نتائج السمات حسب أولوية ثابتة.
9. **التقرير:** يبني `Report Builder` عرضًا عربيًا وبيانات تتبع قابلة للقراءة آليًا من مخرجات المراحل السابقة.

## 4. المعمارية التقنية

```text
┌──────────────────────────────────────────────┐
│ Frontend: Arabic RTL HTML / CSS / JavaScript │
└──────────────────────┬───────────────────────┘
                       │ HTTP / JSON
                       ▼
┌──────────────────────────────────────────────┐
│ FastAPI Backend                              │
│ POST /api/v1/verify + polling                │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ VerificationOrchestrator                     │
├──────────────────────────────────────────────┤
│ Claim Extraction / Classification            │ ← Claude + Pydantic
│ Deterministic Source Routing                 │ ← Code
│ Provider Adapters                            │ ← External sources
│ EvidenceCandidate normalization              │ ← Code
│ Record Alignment                             │ ← Code
│ Attribute Validation                         │ ← Code, then closed-evidence
│                                              │   Claude where required
│ Conflict preservation                        │ ← Code
│ Deterministic Decision Engine                │ ← Code only
│ Traceable Report Builder                     │ ← Fixed templates/code
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ In-memory Request State                      │
└──────────────────────────────────────────────┘
```

يشغّل `VerificationOrchestrator` المراحل دون تكرار منطقها. يخدم FastAPI الواجهة والـ API من العملية نفسها. تُحفظ حالة الطلبات في قاموس داخل الذاكرة، ويُستخدم cache داخلي للمزودين داخل العملية.

يستخدم Anthropic في موضعين رئيسيين:

- إنشاء استخراج منظم للمطالبات والسمات.
- التحقق الدلالي من السمات التي لا تكفي لها المقارنة المنظمة، في وضع `closed-evidence` لا يسمح بالاستناد إلى معرفة خارج الأدلة المرسلة.

أما التوجيه، ومحاذاة السجلات، والمقارنات المنظمة، وتجميع التعارض، والقرار النهائي، وبناء التقرير فهي منطق برمجي. **النموذج لا يصدر `Final Decision Status` مباشرة.**

## 5. دورة معالجة الطلب

1. يكتب المستخدم النص في الواجهة العربية.
2. ترسل الواجهة `POST /api/v1/verify` مع الحقل `text`.
3. ينشئ Backend معرفًا بالشكل `verify_...` وحالة `PROCESSING`، ويبدأ المهمة الخلفية.
4. تستدعي مرحلة `ANALYZE_TEXT` مستخرج المطالبات، وتتحقق من المخرجات عبر Pydantic.
5. تحمل كل مطالبة تصنيفًا وسمات واستعلامات بحث مضبوطة.
6. ينشئ `Source Router` خطة استرجاع حسب المجال والنوع والسمات.
7. تنفذ `Provider Adapters` عمليات الاسترجاع غير المتزامنة، ثم تُزال التكرارات وتُنشأ `EvidenceCandidate` records.
8. تفحص مرحلة المحاذاة هوية سجل القرآن أو الحديث وسياق الأدلة التفسيرية والموضوعية.
9. تتحقق `Attribute Validation` من كل سمة مطلوبة بصورة مستقلة.
10. تحفظ مرحلة التجميع الأدلة الداعمة والمناقضة وحالات الغموض.
11. يطبق `Deterministic Decision Engine` قواعد الأولوية على النتائج المنظمة.
12. يبني `Report Builder` تقرير المطالبة والتقرير الإجمالي من قوالب ثابتة.
13. تستعلم الواجهة دوريًا من `GET /api/v1/verify/{request_id}` وتعرض التقدم، والنتائج، والمصادر، والتتبع، وبيانات التكلفة.

حالات الطلب نفسها هي `PROCESSING` و`COMPLETED` و`FAILED`. وخطوات التنفيذ الظاهرة هي `ANALYZE_TEXT` و`RETRIEVE_EVIDENCE` و`ALIGN_EVIDENCE` و`VALIDATE_EVIDENCE` و`MAKE_DECISION` و`BUILD_REPORT`.

## 6. أنواع النتائج

### حالات التحقق من السمة — Attribute Validation Status

| الحالة | المعنى |
|---|---|
| `SUPPORTED` | دليل محاذى يدعم قيمة السمة المطلوبة. |
| `PARTIAL` | الدليل يثبت جزءًا من السمة، لا كاملها. |
| `CONTRADICTED` | دليل محاذى يثبت قيمة غير متوافقة مع السمة. |
| `NOT_FOUND` | لم يوجد دليل مناسب يوفّر الحقل المطلوب. |
| `UNCERTAIN` | الأدلة أو النسبة أو السياق لا تسمح بحسم آمن، أو وُجد دعم وتناقض على السمة نفسها. |

ولتنفيذ مرحلة التحقق نفسها حالات مستقلة: `COMPLETED` و`PARTIAL` و`SKIPPED` و`ERROR`.

### حالات القرار النهائي — Final Decision Status

| الحالة | المعنى |
|---|---|
| `SUPPORTED` | جميع السمات المطلوبة مدعومة. |
| `PARTIALLY_SUPPORTED` | توجد سمة مطلوبة مدعومة جزئيًا دون حالة أعلى أولوية. |
| `CONFLICTING` | يوجد تعارض صريح أو سمة مطلوبة مناقضة. |
| `INSUFFICIENT_EVIDENCE` | دليل مطلوب مفقود أو غامض. |
| `REQUIRES_SPECIALIST` | توجد علامة مراجعة مختص أو فشل تنفيذ يجعل القرار الآلي غير آمن. |

الفرق الجوهري أن `Validation Status` يصف علاقة دليل بسمة واحدة، بينما `Final Decision Status` يجمع نتائج جميع السمات المطلوبة للمطالبة وفق قواعد ثابتة.

## 7. المصادر المعرفية المستخدمة

| المجال | المصدر | الاستخدام | الموقع الرسمي |
|---|---|---|---|
| القرآن | Quranpedia | الآيات، معلومات السور، والتفسير عند توفر المسار المناسب | [quranpedia.net](http://quranpedia.net/) |
| الحديث | HadeethEnc | البحث في الحديث وتفاصيل السجل المنظمة | [hadeethenc.com](https://hadeethenc.com/) |
| الحديث | Dorar Hadith | السجل، الراوي، المصدر، والحكم العلمي الصريح | [dorar.net](https://dorar.net/) |
| شرح الحديث | Dorar Hadith Explanation | شرح مرتبط بسجل حديث أب محاذى | [dorar.net](https://dorar.net/) |
| التفسير | Dorar Tafseer | أقسام التفسير وسياقها | [dorar.net](https://dorar.net/) |
| التفسير | Quranpedia | تفسير الآية عند استخدام مساراته | [quranpedia.net](http://quranpedia.net/) |
| الفقه | Dorar Feqhia | مادة فقهية متعلقة بالمطالبة | [dorar.net](https://dorar.net/) |
| العقيدة | Dorar Aqeedah | مادة عقدية متعلقة بموضوع المطالبة | [dorar.net](https://dorar.net/) |
| السيرة والتاريخ | Dorar History | أحداث تاريخية ومادة سيرة | [dorar.net](https://dorar.net/) |
| المحتوى الإسلامي العام | Bayan / Byenah | محتوى المكتبة الإسلامية العام | [byenah.com](https://www.byenah.com/) |

هذه مصادر خارجية؛ يتأثر توفرها بالشبكة، وسياسات الوصول، ومعدلات الطلب، وتغير HTML أو API. بيّنة مشروع مستقل ولا يدعي الانتماء إلى هذه الجهات أو مصادقتها الرسمية عليه.

## 8. آلية التحقق من الأدلة

### Evidence Retrieval مقابل Evidence Verification

`Evidence Retrieval` مرحلة اكتشاف: تبحث adapters وتعيد نتائج مرشحة. أما `Evidence Verification` فتسأل: هل النتيجة تخص السجل المقصود؟ وهل تحتوي على الحقل المطلوب؟ وهل يدعم هذا الحقل القيمة المدعاة أم يناقضها أم لا يكفي لحسمها؟

### EvidenceCandidate

النموذج الموحد `EvidenceCandidate` يحفظ، بحسب ما يعيده المزود: `evidence_id`، و`claim_id`، و`target_attribute_ids`، و`provider`، و`evidence_type`، والنص، والاستعلام، والعنوان، والمصدر، والمؤلف، والراوي، والعالم، والحكم، والمرجع، والصفحة، و`provider_record_id`، و`source_url`، والرتبة، ووقت الاسترجاع، والحقول والبيانات الخام.

### مثال حديث

في المطالبة:

> «إنما الأعمال بالنيات، رواه البخاري عن عمر بن الخطاب»

يمكن أن تنشأ سمات مستقلة لمتن الحديث، والراوي، والمصدر. لا يكفي العثور على حديث قريب في الكلمات لإثبات أن الراوي هو عمر أو أن المصدر هو البخاري. يجب أولًا محاذاة متن الدليل إلى سجل الحديث المقصود، ثم فحص حقول الراوي والمصدر في ذلك السجل. وبهذا يمكن أن تكون سمة النص مدعومة بينما تبقى سمة أخرى غير موجودة أو غير محسومة.

## 9. التعامل مع القرآن

يتعرف النظام إلى سجل القرآن باستخدام السمات المنظمة مثل `QURAN_TEXT` و`SURAH` و`AYAH_NUMBER` أو `AYAH_RANGE`. يسترجع Quranpedia النص أو معلومات السورة أو التفسير وفق نوع المطالبة.

في `quran_record_alignment`:

- يجب أن يكون المرشح من نوع `QURAN_AYAH` عند محاذاة سجل آية.
- تقارن هوية السورة ورقم الآية أو المجال والنص المطبّع.
- يدعم النظام الاقتباس الجزئي ذي المعنى عندما يكون مقطعًا متصلًا من كلمات النص القانوني، وبحد أدنى محافظ للطول والكلمات.
- إذا طابق المرجع سورة وآية محددتين لكن النص المسترجع لا يطابق النص المدعى، تصبح سمات هوية القرآن `CONTRADICTED` عبر `quran_record_alignment`.
- النتيجة من سجل مختلف لا تُستخدم لإثبات المطالبة لمجرد التشابه.

بالنسبة إلى التفسير، يوجه `QURAN_TAFSIR` و`QURAN_INTERPRETATION` إلى `DORAR_TAFSEER` أولًا وQuranpedia عند الحاجة. ويتحقق سياق التفسير من هوية القرآن الأب، بما في ذلك السورة أو الصفحة المتاحة. كما لا يبدأ تفسير تابع من نوع `QURAN_INTERPRETATION` إذا لم تكن محاذاة المطالبة القرآنية الأب `ALIGNED`؛ عند غياب السياق تُحفظ `MISSING_CONTEXT` بدل اختلاق نتيجة.

## 10. التعامل مع الحديث

يوجه النظام الحديث بحسب الغرض:

- متن الحديث أو السجل: HadeethEnc ثم Dorar Hadith.
- الصحة أو الحكم: Dorar Hadith ثم HadeethEnc.
- المعنى أو التفسير: يبدأ من Dorar Hadith، ثم قد يجلب شرحًا تابعًا.

تفحص `hadith_record_alignment` متن الحديث أو معرف السجل. تكون النتيجة `ALIGNED` أو `UNRELATED` أو `UNRESOLVED`. المرشح المقتطع بصورة لا تكفي لإثبات الهوية يبقى `UNRESOLVED` بدل اعتباره مطابقًا.

سمات مثل `NARRATOR` و`SOURCE` و`COLLECTION` و`AUTHENTICITY` لا تُستخدم من سجل حديث غير محاذى عندما تعتمد على سجل المتن. ولا يثبت HadeethEnc صحة الحديث إذا لم يُرجع حكمًا صريحًا. في `AUTHENTICITY` تُحفظ هوية الحديث ونسبة الحكم إلى العالم؛ وإذا حددت المطالبة `asserted_by` فيجب أن يتطابق العالم أو صاحب النسبة. الأحكام لسجلات مختلفة لا تُدمج كأنها حكم واحد.

كذلك، طرق الرواية أو المصادر البديلة لسجلات محاذاة لا تتحول آليًا إلى نفي حتمي للراوي أو المصدر المدعى؛ يعالج الكود نسب الحديث بصورة محافظة.

### اعتماد شرح الحديث

لا يستدعي النظام `DORAR_HADITH_EXPLANATION` بحرية. يلزم:

1. أن تكون المطالبة من نوع `HADITH_MEANING` أو `HADITH_INTERPRETATION`.
2. أن يوجد سجل Dorar Hadith أب محاذى.
3. أن يعلن السجل أن الشرح متاح.
4. أن يتوفر `explanation_id`.
5. أن تتطابق هوية الشرح مع `hadith_id` أو متن الحديث الأب.

إذا فشلت هذه الشروط تُحفظ حالة dependency مثل `PARENT_UNRELATED` أو `EXPLANATION_ID_MISSING` أو `EXPLANATION_IDENTITY_MISMATCH`، ولا يُستخدم الشرح كدليل.

## 11. التفسير والفقه والعقيدة والسيرة والتاريخ

| نوع المطالبة | التوجيه الحالي | حدود التحقق |
|---|---|---|
| `QURAN_TAFSIR` / `QURAN_INTERPRETATION` | Dorar Tafseer ثم Quranpedia | يتطلب سياقًا قرآنيًا مطابقًا، وتُفحص سمة `INTERPRETATION`. |
| `QURAN_CONTEXT` | Dorar Tafseer | يعتمد على توفر المادة وسلامة السياق. |
| `FIQH_RULING` أو مجال `FIQH` | Dorar Feqhia | تُقبل فقط أدلة فقهية متوافقة موضوعيًا، ثم يتحقق الحكم أو النص دلاليًا/منظمًا حسب الحقول. |
| مجال/نوع `AQEEDAH` | Dorar Aqeedah | يلزم وجود سمة قابلة للتحقق، وتُفحص صلة الدليل بالموضوع. |
| `SEERAH` / `ISLAMIC_HISTORY` | Dorar History | تفحص السمات مثل النص والتاريخ والموقع، مع محاذاة الحدث أو الموضوع. |
| مجال `GENERAL` | Bayan | استرجاع مكتبة إسلامية عامة؛ لا يمنح نتيجة الاسترجاع صفة الإثبات تلقائيًا. |

عند `SOURCE_ERROR` في مطالبة سياقية من هذه المجالات تُسجل مرحلة التحقق `ERROR` وفشل تنفيذ؛ لا يحول النظام تعذر المزود إلى `CONTRADICTED`.

## 12. محرك القرار الحتمي

الدالة `decide_claim` تقرأ `EvidenceValidationResponse` والسمات المطلوبة فقط. لا تنفذ I/O، ولا تستدعي مزودًا أو نموذجًا، ولا تعيد تفسير نص الدليل. ترتيب القواعد الفعلي هو:

1. **علامة مراجعة مختص:** `specialist_review_required` تؤدي إلى `REQUIRES_SPECIALIST`.
2. **فشل التحقق:** فشل مطلوب أو `ValidationExecutionStatus.ERROR` يؤدي إلى `REQUIRES_SPECIALIST`.
3. **دعم وتناقض في السمة نفسها:** يؤدي إلى `CONFLICTING`.
4. **سمة مطلوبة مناقضة:** تؤدي إلى `CONFLICTING`؛ ويختلف `reason_code` حسب وجود دعم إيجابي لسمة أخرى.
5. **دليل مطلوب مفقود:** يؤدي إلى `INSUFFICIENT_EVIDENCE`.
6. **دليل غامض:** يؤدي إلى `INSUFFICIENT_EVIDENCE`.
7. **دعم جزئي:** يؤدي إلى `PARTIALLY_SUPPORTED`.
8. **دعم كامل:** إذا كانت كل السمات المطلوبة `SUPPORTED` تكون النتيجة `SUPPORTED`.

لا يُستخدم `validator_confidence` كاحتمال لصدق المطالبة. ويحمل القرار `decision_trace` يبين القواعد التي اختُبرت وما الذي طابق منها.

## 13. التتبع — Traceability

يحافظ النظام على سلسلة الربط من المطالبة إلى السمة ثم الدليل والقرار:

- `evidence_id` معرف داخلي لكل دليل مرشح.
- `provider` يحدد المصدر المسترجع منه.
- `provider_record_id` يحفظ معرف السجل عندما يتوفر.
- `source_url` يحفظ رابط المصدر.
- `text` يحفظ النص الأصلي المسترجع.
- `supporting_evidence_ids` و`contradicting_evidence_ids` يربطان نتيجة السمة بالأدلة.
- `candidate_alignment` و`trace` يوثقان المحاذاة وطريقة التحقق والحقول المقارنة.
- `decision_trace` يوثق تطبيق قواعد القرار.

يبني التقرير مصادره من معرفات الأدلة التي أشارت إليها نتائج التحقق فقط. لذلك لا ينبغي عرض candidate غير محاذى أو غير مستخدم كأنه إثبات. وقد يكون المصدر داعمًا لسمة ومناقضًا لسمة أخرى؛ الدور مرتبط بالسمة، لا بالمصدر ككل.

## 14. الموثوقية والمسؤولية العلمية

- **غياب الدليل ≠ خطأ:** `NOT_FOUND` أو `INSUFFICIENT_EVIDENCE` لا تعنيان بطلان المعلومة.
- **التشابه ≠ دليل:** يلزم إثبات هوية السجل والسياق.
- **Retrieval ≠ Verification:** الاسترجاع يولد candidates، والتحقق وحده يصنف علاقتها بالمطالبة.
- **التعارض لا يُخفى:** تُحفظ الأدلة الداعمة والمناقضة، وقد تكون النتيجة `CONFLICTING`.
- **عدم الحسم مقبول:** الغموض يؤدي إلى `INSUFFICIENT_EVIDENCE`، وفشل التنفيذ أو الحاجة الصريحة للمختص يؤديان إلى `REQUIRES_SPECIALIST`.

> بيّنة أداة مساعدة للبحث والتحقق، ولا يحل محل العلماء أو الجهات الشرعية المختصة.

## 15. التقنيات والأدوات

| التقنية | الاستخدام |
|---|---|
| Python 3.10+ | لغة Backend وسكربتات التقييم والاختبارات |
| FastAPI | API وخدمة ملفات Frontend |
| Uvicorn | ASGI server محليًا وفي الإنتاج |
| Pydantic / pydantic-settings | العقود المنظمة، التحقق، والإعدادات |
| Anthropic Python SDK / Claude | استخراج المطالبات والتحقق الدلالي المغلق على الأدلة |
| HTTPX | اتصالات المزودين غير المتزامنة والاختبارات |
| Requests | retrievers مساعدة لبعض مصادر Dorar |
| Beautiful Soup | تحليل HTML من المزودين |
| HTML / CSS / JavaScript | واجهة عربية RTL دون framework إضافي |
| pytest | اختبارات الوحدة والعقود والقبول والـ live tests الاختيارية |
| Railway | نموذج النشر الموثق باستخدام Uvicorn و`$PORT` |

## 16. هيكل المشروع

```text
bayyinah-ai/
├── backend/
│   ├── app/
│   │   ├── agents/          # Claim Extraction
│   │   ├── api/             # FastAPI routes
│   │   ├── application/     # Orchestrator, state, cost tracking
│   │   ├── config/          # Settings
│   │   ├── decision/        # Deterministic Decision Engine
│   │   ├── models/          # Pydantic contracts
│   │   ├── retrieval/       # Routing, adapters, parsers, cache
│   │   ├── reporting/       # Traceable reports and Arabic templates
│   │   ├── services/        # Claim service
│   │   ├── validation/      # Alignment and attribute validation
│   │   └── main.py          # FastAPI entry point
│   └── tests/               # Automated test suite
├── frontend/                # Arabic RTL web interface
├── evaluation/              # Evaluation scripts and saved artifacts
├── docs/                    # Technical documentation
├── .env.example
├── requirements.txt
└── pytest.ini
```

## 17. متطلبات التشغيل

- Python 3.10 أو أحدث؛ تم التحقق من الاختبارات محليًا على Python 3.10.8.
- اتصال إنترنت للتشغيل الفعلي مع Anthropic والمزودين الخارجيين.
- `ANTHROPIC_API_KEY` صالح لاستخراج المطالبات والتحقق الدلالي.
- وصول شبكي إلى المصادر الخارجية؛ قد تعمل الاختبارات غير الحية دون ذلك لأنها تستخدم mocks وfixtures.
- الحزم المحددة في `requirements.txt`.

## 18. إعداد المشروع محليًا

```bash
git clone https://github.com/jamal2134/bayyinah-ai.git
cd bayyinah-ai
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Linux/macOS:

```bash
source .venv/bin/activate
cp .env.example .env
```

ثم تثبيت الاعتماديات:

```bash
pip install -r requirements.txt
```

ضع القيمة السرية محليًا فقط:

```dotenv
ANTHROPIC_API_KEY=your_key_here
```

لا ترفع `.env` إلى Git.

## 19. متغيرات البيئة

يقرأ `Settings` المتغيرات من بيئة التشغيل أو `.env`. الأسماء التالية مشتقة من `backend/app/config/settings.py`:

| المتغير | مطلوب؟ | الاستخدام | سري؟ |
|---|---:|---|---:|
| `ANTHROPIC_API_KEY` | نعم للتشغيل الحي الكامل | مصادقة استخراج المطالبات والتحقق الدلالي | نعم |
| `ANTHROPIC_WORKSPACE_ID` | شرطي | يرسل header للمفاتيح التي تتطلب workspace | يعامل كحساس |
| `ANTHROPIC_MODEL` | لا | معرف نموذج Anthropic | لا |
| `ANTHROPIC_TIMEOUT_SECONDS` | لا | مهلة طلب النموذج | لا |
| `ANTHROPIC_MAX_RETRIES` | لا | عدد إعادة محاولات النموذج | لا |
| `LOG_LEVEL` | لا | مستوى logging | لا |
| `HTTP_CONNECT_TIMEOUT` | لا | مهلة الاتصال بالمزود | لا |
| `HTTP_READ_TIMEOUT` | لا | مهلة قراءة استجابة المزود | لا |
| `MAX_PROVIDER_QUERY_ATTEMPTS` | لا | الحد الافتراضي لمحاولات استعلام المزود | لا |
| `QURANPEDIA_BASE_URL` | لا | عنوان API لـ Quranpedia | لا |
| `HADEETHENC_BASE_URL` | لا | عنوان API لـ HadeethEnc | لا |
| `DORAR_BASE_URL` | لا | عنوان Dorar الأساسي | لا |
| `BAYAN_BASE_URL` | لا | عنوان Bayan/Byenah الأساسي | لا |
| `DORAR_ENABLED` | لا | تفعيل adapter العام القديم؛ الافتراضي `false` | لا |
| `DORAR_HADITH_ENABLED` | لا | تفعيل Dorar Hadith | لا |
| `DORAR_HADITH_EXPLANATION_ENABLED` | لا | تفعيل شرح الحديث التابع | لا |
| `DORAR_TAFSEER_ENABLED` | لا | تفعيل Dorar Tafseer | لا |
| `DORAR_FEQHIA_ENABLED` | لا | تفعيل Dorar Feqhia | لا |
| `DORAR_AQEEDA_ENABLED` | لا | تفعيل Dorar Aqeedah | لا |
| `DORAR_HISTORY_ENABLED` | لا | تفعيل Dorar History | لا |
| `DORAR_HADITH_MAX_QUERIES` | لا | حد استعلامات الحديث | لا |
| `DORAR_TAFSEER_MAX_QUERIES` | لا | حد استعلامات التفسير | لا |
| `DORAR_FEQHIA_MAX_QUERIES` | لا | حد استعلامات الفقه | لا |
| `DORAR_AQEEDA_MAX_QUERIES` | لا | حد استعلامات العقيدة | لا |
| `DORAR_HISTORY_MAX_QUERIES` | لا | حد استعلامات التاريخ | لا |
| `DORAR_HADITH_MAX_RESULTS` | لا | حد نتائج الحديث | لا |
| `DORAR_FEQHIA_MAX_RESULTS` | لا | حد نتائج الفقه | لا |
| `DORAR_AQEEDA_MAX_RESULTS` | لا | حد نتائج العقيدة | لا |
| `QURANPEDIA_MAX_CONCURRENCY` | لا | تزامن طلبات Quranpedia | لا |
| `HADEETHENC_MAX_CONCURRENCY` | لا | تزامن طلبات HadeethEnc | لا |
| `DORAR_MAX_CONCURRENCY` | لا | تزامن طلبات Dorar | لا |
| `BAYAN_MAX_CONCURRENCY` | لا | تزامن طلبات Bayan | لا |

`ANTHROPIC_WORKSPACE_ID` لا يلزم لكل مفتاح؛ يضاف إلى `anthropic-workspace-id` فقط عندما تكون له قيمة.

## 20. تشغيل النظام

من جذر repository:

```bash
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

- Application: <http://localhost:8000>
- Health: <http://localhost:8000/health>
- OpenAPI: <http://localhost:8000/docs>

## 21. API Endpoints

| Method | Endpoint | الوصف |
|---|---|---|
| `GET` | `/health` | فحص صحة التطبيق من الجذر |
| `GET` | `/api/v1/health` | فحص صحة API |
| `POST` | `/api/v1/verify` | بدء المسار الكامل وإرجاع `request_id` بحالة 202 |
| `GET` | `/api/v1/verify/{request_id}` | متابعة التقدم أو جلب النتيجة النهائية |
| `POST` | `/api/v1/claims/extract` | استخراج المطالبات وتصنيفها |
| `POST` | `/api/v1/retrieval` | استرجاع الأدلة لمطالبة منظمة موجودة |
| `POST` | `/api/v1/verify/retrieve` | استخراج ثم استرجاع مع التوقف قبل validation |
| `POST` | `/api/v1/validation` | محاذاة الأدلة والتحقق من السمات |
| `POST` | `/api/v1/decisions` | إصدار قرار من `EvidenceValidationResponse` |
| `POST` | `/api/v1/decisions/with-claim` | إصدار قرار مع المطالبة لاستبعاد السمات غير المطلوبة |
| `POST` | `/api/v1/reports` | بناء تقرير من المخرجات المنظمة للمراحل السابقة |

تعرض `/docs` عقود الطلب والاستجابة التي يولدها FastAPI من نماذج Pydantic.

## 22. الاختبارات والتحقق

لتشغيل المجموعة الكاملة:

```bash
python -m pytest backend/tests -q
```

آخر نتيجة تحقق محلية بتاريخ 6 أكتوبر 2026:

```text
338 collected
337 passed
1 skipped (opt-in live-provider test)
0 failed
```

هذه اختبارات software وcontract وacceptance، وليست نسبة دقة شرعية أو `factual accuracy`.

تشمل المستودع اختبارات ومصنوعات تقييم لـ:

- عقود المزودين وparsers باستخدام fixtures.
- فشل المزود، والمهلات، والاستجابات غير الصالحة.
- المحاذاة القرآنية، والاقتباس الجزئي، والتفسير متعدد الآيات.
- محاذاة الحديث، وتجميع الصحة، وربط شرح الحديث بالسجل الأب.
- `Mixed E2E` للمجالات المختلفة.
- حالات مضبوطة صحيحة وadversarial في `final_demo_acceptance`.
- فحوص traceability، وunsupported inference، ومنع تسرب الدليل بين المجالات.
- `Golden Live` محفوظ يعتمد على توفر النموذج والمزودين وقت تشغيله.

تسجل وثيقة القبول المضبوط الحالية 30 قرارًا مبنيًا على الأدلة مع `unsupported_inference_count = 0` و`evidence_traceability = 1.0`. هذه نتائج سيناريوهات fixture-backed مضبوطة، وليست ضمانًا عامًا للدقة الواقعية.

للاختبار الحي الاختياري:

```powershell
$env:RUN_LIVE_RETRIEVAL_TESTS = "1"
python -m pytest -m live backend/tests/test_live_retrieval.py -q
```

## 23. النشر على Railway

النموذج التشغيلي الموثق:

```text
GitHub Repository
       ↓
Railway / Python build environment
       ↓
FastAPI served by Uvicorn
```

Start Command:

```bash
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
```

Health Check:

```text
/health
```

- يوفر Railway قيمة `PORT` وقت التشغيل.
- يوضع `ANTHROPIC_API_KEY` وبقية إعدادات الإنتاج في Railway Variables.
- لا يُرفع `.env`.
- يُنصح حاليًا بعملية/نسخة `process/replica` واحدة لأن حالة الطلبات داخل الذاكرة ولا تشترك بين النسخ.
- يلزم مخزن مشترك دائم قبل horizontal scaling.

**رابط النسخة المباشرة:** [ضع رابط النسخة المباشرة هنا]

لم يوجد رابط Production معلن في repository وقت إعداد هذه الوثيقة.

## 24. الأمان

- تحفظ مفاتيح API في server-side environment variables.
- ملف `.env` مدرج في `.gitignore` ولا يُرسل إلى Frontend.
- لا يحتوي Frontend على مفتاح Anthropic أو منطق مصادقة المزودين.
- لا تسجل خدمة الاستخراج النص الكامل المدخل أو بيانات الاعتماد ضمن metadata التشغيلية.
- تُعامل مدخلات المستخدم كنص غير موثوق في prompts.
- يستخدم التحقق الدلالي نمط `closed-evidence` ويُمنع من ملء الفجوات من معرفة النموذج المحفوظة.
- تمر مخرجات النموذج عبر عقود Pydantic قبل استخدامها.

## 25. القيود الحالية

- يعتمد الاسترجاع الحي على الشبكة وتوفر المزودين وسياساتهم.
- قد يتطلب تغير HTML أو API تحديث parsers وadapters.
- يعتمد استخراج المطالبات وبعض التحقق الدلالي على Anthropic.
- جودة النتيجة محدودة بجودة الأدلة التي يمكن استرجاعها ومحاذاتها.
- حالة طلبات التحقق وcache داخل الذاكرة ومحلية للعملية.
- إعادة تشغيل الخادم تفقد الطلبات السابقة، والـ workers أو replicas لا تشترك في الحالة.
- حالات الغموض أو فشل التنفيذ قد تحتاج إلى مختص.
- الأداة ليست بديلًا عن الحكم العلمي المؤهل.

## 26. استكشاف الأخطاء — Troubleshooting

| المشكلة | السبب المحتمل | الحل |
|---|---|---|
| `Missing API key` أو تعذر بدء الاستخراج | `ANTHROPIC_API_KEY` غير مضبوط | أنشئ `.env` من `.env.example` واضبط المفتاح محليًا دون طباعته أو رفعه. |
| Anthropic authentication/workspace error | مفتاح غير صالح أو يحتاج `ANTHROPIC_WORKSPACE_ID` | تحقق من صلاحية المفتاح واضبط workspace فقط إذا كان حسابك يتطلبه. |
| Anthropic model access error | `ANTHROPIC_MODEL` غير متاح للمفتاح/workspace | اختر model ID متاحًا للحساب. |
| Provider timeout | الشبكة بطيئة أو المزود لا يستجيب | راجع `HTTP_CONNECT_TIMEOUT` و`HTTP_READ_TIMEOUT`، ثم أعد المحاولة. |
| Provider HTTP/source error | حظر، rate limit، أو تغير endpoint/HTML | راجع provider trace وstatus؛ لا تعتبره تناقضًا في المحتوى. |
| Dorar unavailable | تعذر الوصول أو تغير صفحة المصدر | تحقق من `DORAR_*_ENABLED` والاتصال، وحدّث parser عند تغير العقد. |
| Port already in use | عملية أخرى تستخدم 8000 | استخدم منفذًا آخر مثل `--port 8001`. |
| `ModuleNotFoundError: app` | تشغيل Uvicorn دون مسار التطبيق | شغّل من الجذر مع `--app-dir backend`. |
| Verification request not found بعد restart | `REQUESTS` مخزن داخل الذاكرة | أعد إرسال الطلب؛ يلزم مخزن دائم للحفاظ على الحالة عبر restart. |
| طلب يبقى غير محسوم | دليل مفقود/غامض أو validation غير متاح | راجع `retrieval_status` و`warnings` و`execution_failures` ومصادر التقرير. |

## 27. الترخيص

لم يتم تحديد ترخيص مفتوح المصدر للمشروع حتى الآن. وبالتالي لا ينبغي افتراض منح حقوق إعادة الاستخدام أو التعديل أو إعادة التوزيع إلى أن تتم إضافة ملف `LICENSE` رسمي.

## 28. نسب المصادر وحقوق المحتوى

يسترجع المشروع أو يعالج مواد من:

- Quranpedia: <http://quranpedia.net/>
- Dorar: <https://dorar.net/>
- HadeethEnc: <https://hadeethenc.com/>
- Bayan / Byenah: <https://www.byenah.com/>

تظل نسبة المحتوى والبيانات وحقوقها إلى مصادرها ومؤلفيها وأصحابها. استخدام هذه المصادر لا يعني وجود affiliation أو endorsement أو اعتماد رسمي لمشروع بيّنة من أي مزود.

## 29. دليل سريع للمطور — Quick Start

1. استنسخ المشروع وانتقل إلى مجلده:

   ```bash
   git clone https://github.com/jamal2134/bayyinah-ai.git
   cd bayyinah-ai
   ```

2. أنشئ وفعّل virtual environment:

   ```bash
   python -m venv .venv
   ```

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. ثبّت الاعتماديات:

   ```bash
   pip install -r requirements.txt
   ```

4. أنشئ `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

5. أضف محليًا:

   ```dotenv
   ANTHROPIC_API_KEY=your_key_here
   ```

6. شغّل التطبيق:

   ```bash
   uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
   ```

7. افتح <http://localhost:8000>.

8. شغّل الاختبارات:

   ```bash
   python -m pytest backend/tests -q
   ```

## 30. الخاتمة

لا يحاول بيّنة فقط العثور على نتيجة مشابهة، بل يحاول الإجابة عن سؤال أكثر صرامة:

> **هل الدليل المسترجع يثبت هذه المطالبة فعلًا؟**

من معلومة تبدو صحيحة...  
إلى نتيجة يمكن إثباتها وتتبعها.

---

**تنبيه نهائي:** بيّنة أداة مدعومة بالذكاء الاصطناعي للمساعدة في البحث والتحقق. لا يحل محل العلماء المؤهلين أو المؤسسات الشرعية المعتمدة، ولا ينبغي الاعتماد على مخرجاته وحدها في الفتاوى أو الأحكام العقدية أو القرارات الدينية الحساسة.
