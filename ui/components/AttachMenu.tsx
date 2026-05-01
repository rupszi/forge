/**
 * AttachMenu — the "+" button next to the prompt input.
 *
 * Mirrors Claude Code's attach menu but tied to Forge's surfaces:
 *
 *   Add files or photos   → attach files to the next sprint's prompt
 *   Add folder            → import a folder into the worktree's
 *                           input area (read-only by default)
 *   Slash commands        → opens the slash-command palette
 *                           (/help, /clear, /model, /memory, etc.)
 *   Connectors      ›     → submenu listing enabled connectors;
 *                           click to "request use this turn"
 *                           (the planner sees them as available tools)
 *   Add plugins…          → opens the plugin gallery (skills + connectors
 *                           + LLM adapters from ~/.forge/plugins / skills / llms)
 *
 * Each item dispatches a WebSocket event the daemon understands:
 *
 *   attach.files          → expects multipart upload via separate POST
 *   attach.folder         → reads folder contents, scopes write to worktree
 *   slash.open            → toggles the slash palette
 *   connector.activate    → marks a connector as active for the next sprint
 *   plugin.gallery        → opens the gallery panel
 */

import React, { useEffect, useRef, useState } from "react";

export type AttachAction =
  | { type: "files"; files: File[] }
  | { type: "folder" }
  | { type: "slash" }
  | { type: "connector"; name: string }
  | { type: "plugins" };

export type AttachMenuProps = {
  enabledConnectors: string[];
  onAction: (action: AttachAction) => void;
};

export function AttachMenu({ enabledConnectors, onAction }: AttachMenuProps) {
  const [open, setOpen] = useState(false);
  const [showConnectors, setShowConnectors] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setShowConnectors(false);
      }
    }
    if (open) {
      window.addEventListener("click", onClick);
      return () => window.removeEventListener("click", onClick);
    }
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="p-1.5 rounded text-gray-400 hover:bg-[#1a1a24] hover:text-gray-200"
        title="Attach"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute bottom-full mb-2 left-0 w-56 rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50">
          <ul className="py-1">
            <Item
              icon="📎"
              label="Add files or photos"
              onClick={() => {
                fileInput.current?.click();
              }}
            />
            <Item
              icon="📁"
              label="Add folder"
              onClick={() => {
                onAction({ type: "folder" });
                setOpen(false);
              }}
            />
            <Item
              icon="/"
              label="Slash commands"
              onClick={() => {
                onAction({ type: "slash" });
                setOpen(false);
              }}
            />
            <Item
              icon="◰"
              label="Connectors"
              chevron
              onClick={() => setShowConnectors((s) => !s)}
            />
            {showConnectors && enabledConnectors.length > 0 && (
              <ul className="border-t border-[#1e1e2e] py-1 max-h-48 overflow-y-auto">
                {enabledConnectors.map((c) => (
                  <li key={c}>
                    <button
                      onClick={() => {
                        onAction({ type: "connector", name: c });
                        setOpen(false);
                      }}
                      className="w-full px-3 py-1.5 text-left text-xs text-gray-300 hover:bg-[#1a1a24]"
                    >
                      <span className="font-mono text-teal-400">●</span> {c}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {showConnectors && enabledConnectors.length === 0 && (
              <li className="px-3 py-2 text-xs text-gray-500">
                No connectors enabled. Run <code className="text-gray-300">forge wizard</code>.
              </li>
            )}
            <li className="border-t border-[#1e1e2e]">
              <Item
                icon="🔌"
                label="Add plugins…"
                onClick={() => {
                  onAction({ type: "plugins" });
                  setOpen(false);
                }}
              />
            </li>
          </ul>
        </div>
      )}

      <input
        ref={fileInput}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onAction({ type: "files", files });
          setOpen(false);
        }}
      />
    </div>
  );
}

function Item({
  icon,
  label,
  chevron,
  onClick,
}: {
  icon: string;
  label: string;
  chevron?: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-[#1a1a24]"
      >
        <span className="flex items-center gap-2 text-sm text-gray-200">
          <span className="text-gray-500 w-4">{icon}</span>
          {label}
        </span>
        {chevron && <span className="text-gray-500 text-xs">›</span>}
      </button>
    </li>
  );
}
