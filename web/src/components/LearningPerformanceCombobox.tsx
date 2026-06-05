import { useEffect, useRef, useState } from "react";

interface LpEntry {
  value: string;
  instruction?: string;
  科目?: string;
}

interface Props {
  options: LpEntry[];
  selected: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}

export default function LearningPerformanceCombobox({
  options,
  selected,
  onChange,
  placeholder = "（沿用題組設定）",
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = options.filter((o) => {
    if (selected.includes(o.value)) return false;
    if (!query) return true;
    const q = query.toLowerCase();
    return o.value.toLowerCase().includes(q) || (o.instruction ?? "").toLowerCase().includes(q);
  });

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  function select(value: string) {
    onChange([...selected, value]);
    setQuery("");
    setActiveIndex(0);
    inputRef.current?.focus();
  }

  function remove(value: string) {
    onChange(selected.filter((v) => v !== value));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && query === "" && selected.length > 0) {
      remove(selected[selected.length - 1]);
      return;
    }
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "Enter") {
        setOpen(true);
        e.preventDefault();
      }
      return;
    }
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown") {
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      setActiveIndex((i) => Math.max(i - 1, 0));
      e.preventDefault();
    } else if (e.key === "Enter") {
      if (filtered[activeIndex]) {
        select(filtered[activeIndex].value);
      }
      e.preventDefault();
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div
        className="flex min-h-[2rem] flex-wrap items-center gap-1 rounded border bg-white px-1.5 py-1 text-sm focus-within:ring-1 focus-within:ring-blue-400"
        onClick={() => { inputRef.current?.focus(); setOpen(true); }}
      >
        {selected.map((v) => {
          const entry = options.find((o) => o.value === v);
          return (
            <span
              key={v}
              className="inline-flex items-center gap-1 rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800"
            >
              {v}
              {entry?.instruction && (
                <span className="font-normal text-blue-600 hidden sm:inline">：{entry.instruction}</span>
              )}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); remove(v); }}
                className="ml-0.5 rounded hover:bg-blue-200"
                aria-label={`移除 ${v}`}
              >
                ×
              </button>
            </span>
          );
        })}
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder={selected.length === 0 ? placeholder : "搜尋…"}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="min-w-[6rem] flex-1 bg-transparent outline-none text-sm placeholder:text-gray-400"
        />
      </div>

      {open && filtered.length > 0 && (
        <ul className="absolute z-20 mt-0.5 max-h-52 w-full overflow-y-auto rounded border bg-white py-1 shadow-md text-sm">
          {filtered.map((o, idx) => (
            <li
              key={o.value}
              onMouseDown={(e) => { e.preventDefault(); select(o.value); }}
              onMouseEnter={() => setActiveIndex(idx)}
              className={`flex cursor-pointer items-start gap-2 px-3 py-1.5 ${
                idx === activeIndex ? "bg-blue-50" : ""
              }`}
            >
              <span className="shrink-0 font-mono font-semibold text-gray-800">{o.value}</span>
              {o.instruction && (
                <span className="text-gray-500 text-xs leading-5">：{o.instruction}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {open && query && filtered.length === 0 && (
        <div className="absolute z-20 mt-0.5 w-full rounded border bg-white px-3 py-2 text-sm text-gray-400 shadow-md">
          無符合結果
        </div>
      )}
    </div>
  );
}
