# Explicit 情境子類別 is never silently replaced

An explicitly supplied 情境子類別 is a 釘選 value. When a request also supplies 情境, validation rejects the request if the 情境子類別's parent is not among those 情境 values, naming both parameters and explaining the incompatibility. When 情境 is omitted, sampling constrains the 情境 draw to the 情境子類別's parent. Generation never silently substitutes a different 情境子類別.

## Considered Options

Deriving 情境 from 情境子類別 even when the request explicitly supplied an incompatible 情境 was rejected because it would silently replace another 釘選 value. Surfacing the substituted 情境子類別 after generation was also rejected because 發送前確認 promises that the displayed 釘選 value is what generation uses.

## Consequences

Callers must correct incompatible 情境 and 情境子類別 values before generation can begin. A request that supplies only 情境子類別 remains valid, and its parent determines the sampled 情境, preserving the submitted 情境子類別 across the pipeline.
