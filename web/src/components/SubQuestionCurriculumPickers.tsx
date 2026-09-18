import { useId, useMemo, useState } from "react";

export interface SearchPickerEntry {
  value: string;
  instruction?: string;
  科目?: string;
}

export function SearchPicker({
  available,
  selected,
  onChange,
  placeholder,
  id,
  maxSelected,
  disabledValues,
  hint,
}: {
  available: SearchPickerEntry[];
  selected: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  id?: string;
  maxSelected?: number;
  /** #840: values shown disabled (never hidden) — a value already in `selected` is unaffected. */
  disabledValues?: Set<string>;
  /** #840: one hint line explaining why some option is disabled; renders no element when null/undefined. */
  hint?: string | null;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;

  const filtered = useMemo(() => {
    if (!query.trim() || (maxSelected !== undefined && selected.length >= maxSelected)) return [];
    const q = query.toLowerCase();
    return available
      .filter((item) => !selected.includes(item.value))
      .filter(
        (item) =>
          item.value.toLowerCase().includes(q) ||
          (item.instruction ?? "").toLowerCase().includes(q),
      )
      .slice(0, 10);
  }, [available, maxSelected, selected, query]);

  function handleSelect(value: string) {
    if (maxSelected !== undefined && selected.length >= maxSelected) return;
    if (disabledValues?.has(value)) return;
    onChange([...selected, value]);
    setQuery("");
    setOpen(false);
  }

  function handleRemove(value: string) {
    onChange(selected.filter((v) => v !== value));
  }

  return (
    <div className="relative">
      <input
        id={id}
        type="text"
        value={query}
        autoComplete="off"
        placeholder={placeholder ?? "搜尋..."}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => { if (query) setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        aria-describedby={hintId}
        className="block w-full border rounded px-2 py-1 text-sm"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-10 mt-0.5 w-full rounded border border-gray-200 bg-white shadow-md max-h-48 overflow-y-auto">
          {filtered.map((item) => {
            const isDisabled = disabledValues?.has(item.value) ?? false;
            return (
              <button
                key={item.value}
                type="button"
                disabled={isDisabled}
                aria-disabled={isDisabled}
                onMouseDown={() => handleSelect(item.value)}
                className={`block w-full px-2 py-1.5 text-left text-xs ${
                  isDisabled ? "cursor-not-allowed text-gray-400" : "hover:bg-gray-100"
                }`}
              >
                <span className="font-medium">{item.value}</span>
                {item.instruction && (
                  <span className="ml-1 text-gray-500">：{item.instruction}</span>
                )}
              </button>
            );
          })}
        </div>
      )}
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-amber-700">
          {hint}
        </p>
      )}
      {selected.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {selected.map((code) => {
            const item = available.find((a) => a.value === code);
            return (
              <span
                key={code}
                className="inline-flex items-center gap-0.5 rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700 border border-blue-200"
              >
                <span className="font-medium">{code}</span>
                {item?.instruction && (
                  <span className="text-blue-500">
                    ：{item.instruction.length > 20 ? item.instruction.slice(0, 20) + "…" : item.instruction}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => handleRemove(code)}
                  className="ml-0.5 text-blue-400 hover:text-blue-600"
                >
                  ×
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

export interface SubQuestionCurriculumPickersProps {
  availableLearningPerformance: SearchPickerEntry[];
  availableLearningContent: SearchPickerEntry[];
  filteredLpPool?: string[];
  learningPerformance?: string[];
  learningContent?: string[];
  onLearningPerformanceChange: (values: string[] | undefined) => void;
  onLearningContentChange: (values: string[] | undefined) => void;
  /** #840: 學習內容 codes the chosen/remaining 內容領域 does not admit — shown disabled, never dropped. */
  learningContentDisabledValues?: Set<string>;
  /** #840: hint naming why some 學習內容 codes above are disabled. */
  learningContentHint?: string | null;
}

export default function SubQuestionCurriculumPickers({
  availableLearningPerformance,
  availableLearningContent,
  filteredLpPool,
  learningPerformance = [],
  learningContent = [],
  onLearningPerformanceChange,
  onLearningContentChange,
  learningContentDisabledValues,
  learningContentHint,
}: SubQuestionCurriculumPickersProps) {
  const visibleLearningPerformance = filteredLpPool === undefined
    ? availableLearningPerformance
    : availableLearningPerformance.filter((entry) => filteredLpPool.includes(entry.value));
  const visibleLearningContent = availableLearningContent;
  const visibleLearningPerformanceValues = filteredLpPool === undefined
    ? learningPerformance
    : learningPerformance.filter((value) => filteredLpPool.includes(value));
  const visibleLearningContentValues = learningContent;

  if (visibleLearningPerformance.length === 0 && visibleLearningContent.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs text-gray-500">留空 = 沿用全域設定</p>
      {visibleLearningPerformance.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-0.5">學習表現 (留空沿用全域)</p>
                  <SearchPicker
                    available={visibleLearningPerformance}
                    selected={visibleLearningPerformanceValues}
                    onChange={(values) => onLearningPerformanceChange(values.length ? values : undefined)}
                    placeholder="搜尋學習表現..."
                  />
        </div>
      )}
      {visibleLearningContent.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-0.5">學習內容 (留空沿用全域)</p>
                  <SearchPicker
                    available={visibleLearningContent}
                    selected={visibleLearningContentValues}
                    onChange={(values) => onLearningContentChange(values.length ? values : undefined)}
                    placeholder="搜尋學習內容..."
                    disabledValues={learningContentDisabledValues}
                    hint={learningContentHint}
                  />
        </div>
      )}
    </div>
  );
}
