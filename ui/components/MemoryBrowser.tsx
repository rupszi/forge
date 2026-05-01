"use client";

import { useState } from "react";
import type { KnowledgeItem } from "@/lib/types";

interface Props {
  items: KnowledgeItem[];
  onSearch: (query: string) => void;
  onAdd: (category: string, topic: string, content: string) => void;
  onDelete: (id: number) => void;
}

export function MemoryBrowser({ items, onSearch, onAdd, onDelete }: Props) {
  const [query, setQuery] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newCat, setNewCat] = useState("gotcha");
  const [newTopic, setNewTopic] = useState("");
  const [newContent, setNewContent] = useState("");

  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
      <h3 className="text-sm font-semibold text-gray-400 mb-3">Knowledge Base</h3>

      <div className="flex gap-2 mb-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch(query)}
          placeholder="Search..."
          className="flex-1 px-2 py-1 text-xs rounded bg-[#0a0a0f] border border-[#1e1e2e] text-white placeholder-gray-600 focus:outline-none focus:border-purple-600"
        />
        <button onClick={() => onSearch(query)} className="px-2 py-1 text-xs rounded bg-purple-800/40 text-purple-300 hover:bg-purple-800/60">
          Search
        </button>
        <button onClick={() => setShowAdd(!showAdd)} className="px-2 py-1 text-xs rounded bg-green-800/40 text-green-300 hover:bg-green-800/60">
          +
        </button>
      </div>

      {showAdd && (
        <div className="mb-3 p-2 rounded bg-[#0a0a0f] space-y-1">
          <div className="flex gap-1">
            <select value={newCat} onChange={(e) => setNewCat(e.target.value)} className="px-1 py-0.5 text-xs rounded bg-[#12121a] border border-[#1e1e2e] text-gray-300">
              <option value="gotcha">gotcha</option>
              <option value="solution">solution</option>
              <option value="pattern">pattern</option>
              <option value="rule">rule</option>
            </select>
            <input value={newTopic} onChange={(e) => setNewTopic(e.target.value)} placeholder="topic" className="flex-1 px-1 py-0.5 text-xs rounded bg-[#12121a] border border-[#1e1e2e] text-white placeholder-gray-600" />
          </div>
          <div className="flex gap-1">
            <input value={newContent} onChange={(e) => setNewContent(e.target.value)} placeholder="content" className="flex-1 px-1 py-0.5 text-xs rounded bg-[#12121a] border border-[#1e1e2e] text-white placeholder-gray-600" />
            <button onClick={() => { onAdd(newCat, newTopic, newContent); setNewContent(""); }} className="px-2 py-0.5 text-xs rounded bg-green-600 text-white">
              Add
            </button>
          </div>
        </div>
      )}

      <div className="space-y-1 max-h-60 overflow-y-auto">
        {items.map((item) => (
          <div key={item.id} className="flex items-start gap-2 p-1.5 rounded hover:bg-[#0a0a0f] group">
            <span className="text-[10px] text-gray-600 shrink-0">[{item.category}]</span>
            <span className="text-xs text-gray-400 flex-1">{item.content}</span>
            <div className="flex items-center gap-1 shrink-0">
              <span className="text-[10px] text-gray-600">{(item.confidence * 100).toFixed(0)}%</span>
              <button onClick={() => onDelete(item.id)} className="text-[10px] text-red-600 opacity-0 group-hover:opacity-100">
                x
              </button>
            </div>
          </div>
        ))}
        {items.length === 0 && <p className="text-xs text-gray-600 text-center py-4">No items. Search or add knowledge.</p>}
      </div>
    </div>
  );
}
