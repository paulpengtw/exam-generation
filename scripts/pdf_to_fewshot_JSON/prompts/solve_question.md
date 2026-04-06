# Prompt: Solve and Structure a Math Question

You are creating a few-shot training example for a Taiwan junior high school math exam question generator.

## Your Task

Given a parsed exam question, produce a complete, structured representation that:
1. Confirms or corrects the answer
2. Provides clear step-by-step solution
3. Classifies the question metadata
4. Generates chart/figure specification if needed

## Output Format

Return a JSON object (not an array):

```json
{
  "description": "Brief Chinese topic label (5-15 characters, e.g. '二次函數頂點坐標')",
  "情境": "one of: 個人/社會時事/科學/職業/建築與藝術/數學文字情境",
  "題型種類": "單一題 or 題組題",
  "題型": "one of: 選擇題/是非題/封閉式建構反應題/開放式建構反應題",
  "數學思考": ["one or more of: 形成/運用/詮釋評估"],
  "題目": ["line 1 of question", "line 2", "(A) ...", "(B) ...", "(C) ...", "(D) ..."],
  "正確解題分析": [
    "正確答案：(X)",
    "【步驟一：...】explanation",
    "【步驟二：...】explanation"
  ],
  "style": "text_only or with_chart or with_image",
  "chart_spec": null
}
```

If `style` is `with_chart` or `with_image`, include `chart_spec`:

```json
"chart_spec": {
  "chart_type": "one of: histogram/boxplot/line_chart/pie_chart/geometry/table",
  "title": "chart title in Chinese",
  "data": { ... chart-type-specific data ... },
  "labels": { "x": "x-axis label", "y": "y-axis label" },
  "description": "for geometry: spatial description to help render the figure"
}
```

## Chart Spec Examples by Type

**histogram**: `{"bins": ["0~30","30~60",...], "counts": [15,35,...]}`

**boxplot**: `{"ClassName": {"min":40,"Q1":55,"median":70,"Q3":80,"max":95},...}`

**line_chart**: `{"x_label":"年份","y_label":"%","series":[{"name":"韓國","points":[[1970,4],...]}],"reference_lines":[{"y":14,"label":"..."}]}`

**pie_chart**: `{"segments":[{"label":"紅","angle":120,"color":"red"},...]}`

**geometry**: `{"shapes":[...],"description":"spatial layout","key_points":{"A":[0,0],...},...}` — include any coordinates, dimensions, or constraints visible in the figure

**table**: `{"headers":["col1","col2"],"rows":[["r1c1","r1c2"],...]}` or multiple tables as `{"table1":{...},"table2":{...}}`

## Classification Guidelines

**情境**:
- 個人: personal daily life (shopping, cooking, personal decisions)
- 社會時事: social/news topics (population data, public policy, consumer products)
- 科學: science context (physics, biology, measurement)
- 職業: work/business context
- 建築與藝術: architecture, art, design
- 數學文字情境: pure math scenario (spinners, dice, abstract geometric shapes)

**數學思考**:
- 形成 (Formulate): setting up a model, identifying variables, writing equations
- 運用 (Apply): executing a procedure, computing, applying a formula
- 詮釋評估 (Interpret): reading a graph, comparing results, making judgments

**style**:
- `text_only`: question is entirely text, no diagram needed
- `with_chart`: needs a statistical chart (histogram, line chart, bar chart, pie, boxplot) or data table
- `with_image`: needs a geometric figure, coordinate plane diagram, or other spatial illustration

## Solution Format

- Start `正確解題分析` with `"正確答案：(X)"` for multiple choice or `"正確答案：[value]"` for open-ended
- Use `【步驟N：topic】` headers to organize steps
- Show all calculations explicitly
- For wrong answer options in multiple choice, briefly explain why they are incorrect
