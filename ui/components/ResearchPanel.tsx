"use client";

interface ResearchItem {
  query: string;
  url: string;
  title: string;
  content: string;
  relevance: number;
}

interface Props {
  items: ResearchItem[];
  onSaveToKB?: (item: ResearchItem) => void;
}

export function ResearchPanel({ items, onSaveToKB }: Props) {
  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
      <h3 className="text-sm font-semibold text-gray-400 mb-3">Research</h3>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {items.map((item, i) => (
          <div key={i} className="p-2 rounded bg-[#0a0a0f]">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-300 font-medium">{item.title}</span>
              <span className="text-[10px] text-gray-600">{(item.relevance * 100).toFixed(0)}%</span>
            </div>
            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{item.content}</p>
            {item.url && <a href={item.url} target="_blank" rel="noopener" className="text-[10px] text-purple-400 hover:underline">{item.url}</a>}
            {onSaveToKB && (
              <button onClick={() => onSaveToKB(item)} className="mt-1 text-[10px] text-teal-400 hover:text-teal-300">
                Save to KB
              </button>
            )}
          </div>
        ))}
        {items.length === 0 && <p className="text-xs text-gray-600 text-center py-4">No research results.</p>}
      </div>
    </div>
  );
}
