# 從屬參數 rules ship as data in the schema payload

A 從屬參數 is a setting whose legal range is fixed by another setting's resolved value — 情境子類別 by 情境, 學習內容/學習表現 by 科目, and for 公民與社會/跨科 學習內容 also by 內容領域. The 科目→prefix rule was hardcoded on both client and server and drifted (#584); the other two already shipped in the schema payload and did not. We decide (#588) that **all 從屬參數 rules are data in the schema payload, read by both 預抽 and validation**: each dependent entry carries its admitting parent values keyed by parent setting, so the server does the join once at the source and the client needs one generic filter for every 從屬參數, present and future. 內容領域 → 學習內容 is a binding 從屬參數, not advisory; a child may have several parents and its range is their intersection, so 預抽 order is a dependency order.

## Considered options

A drift-guard test over two copies, or a build-time generated constant, were rejected because the 科目 buckets belong to curriculum data operators swap at runtime (`SOCIAL_STUDIES_CURRICULUM_DIR`); a compile-time contract would freeze a rule the data is allowed to change. Shipping the raw maps and letting the client join was rejected in favour of pre-joined admitting-parent tags, which make the observed drift impossible rather than detectable.
