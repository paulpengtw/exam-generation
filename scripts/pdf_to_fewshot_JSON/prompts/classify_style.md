# Prompt: Classify Question Style

Given a parsed math question and its figure description, determine which visual style it requires.

## Output Format

Return a JSON object:

```json
{
  "style": "text_only or with_chart or with_image",
  "reasoning": "brief explanation"
}
```

## Rules

**text_only**: The question can be fully understood and answered from text alone. No diagram, chart, or figure is needed. Pure algebraic, arithmetic, or combinatorics problems typically fall here.

**with_chart**: The question involves:
- A statistical chart (histogram, bar chart, line chart, pie chart, boxplot)
- A data table (e.g. pricing tables, schedule tables, survey result tables)
- Any visual that is primarily about data/numbers rather than geometry

**with_image**: The question involves:
- A geometric figure (triangles, circles, polygons, 3D shapes)
- A coordinate plane with plotted points, lines, or curves
- A real-world spatial diagram (shadow/light problems, floor plans, bridge diagrams)
- Any figure that requires understanding spatial relationships

## Decision Guidance

If the question says "如圖" (as shown in the figure), it needs `with_image`.
If the question references "如表" (as shown in the table) or "如圖" where the figure is clearly a statistical chart, use `with_chart`.
If the question is purely computational with no visual aid, use `text_only`.

Note: The figure description from the previous parsing step is your primary signal. If the figure description is null or says "no figure", classify as `text_only` unless the question clearly implies a data table.
