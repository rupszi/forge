"use client";

import { useEffect, useState } from "react";

export type ProjectBarProps = {
  folderPath: string;
  folderIsGit: boolean;
  branches: string[];
  currentBranch: string | null;
  onConnect: (path: string) => void;
  onBrowse: () => void;
  onSelectBranch: (path: string, branch: string, create?: boolean) => void;
  onInit: (path: string) => void;
};

/**
 * Connect a folder (empty or existing), see its branches, and pick which one to
 * work on. "Browse…" pops the OS-native folder dialog (the daemon opens Finder
 * / zenity on your machine and returns the path). You can also type/paste a
 * path. Empty or non-git folders get an "Initialize git" action.
 */
export function ProjectBar(props: ProjectBarProps) {
  const {
    folderPath,
    folderIsGit,
    branches,
    currentBranch,
    onConnect,
    onBrowse,
    onSelectBranch,
    onInit,
  } = props;
  const [path, setPath] = useState(folderPath);
  const [newBranch, setNewBranch] = useState("");

  useEffect(() => setPath(folderPath), [folderPath]);

  return (
    <div className="mb-4 p-3 rounded-lg bg-[#0e0e16] border border-[#1e1e2e] flex flex-col gap-2">
      {/* Folder row */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-gray-500 w-14">Folder</span>
        <input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onConnect(path)}
          placeholder="/path/to/your/project (empty or existing)"
          className="flex-1 px-2 py-1 rounded bg-[#12121a] border border-[#1e1e2e] text-gray-200 text-xs font-mono focus:outline-none focus:border-purple-600"
        />
        <button
          onClick={onBrowse}
          title="Open the native folder picker"
          className="px-3 py-1 text-xs rounded bg-[#1a1a24] text-gray-200 hover:bg-[#22222e] border border-[#1e1e2e]"
        >
          Browse…
        </button>
        <button
          onClick={() => onConnect(path)}
          className="px-3 py-1 text-xs rounded bg-purple-600 text-white hover:bg-purple-500"
        >
          Connect
        </button>
      </div>

      {/* Branch row */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-gray-500 w-14">Branch</span>
        {!folderIsGit ? (
          <>
            <span className="text-[11px] text-amber-400">Not a git repo.</span>
            <button
              onClick={() => onInit(path)}
              className="px-2 py-1 text-xs rounded bg-[#1a1a24] text-gray-200 hover:bg-[#22222e] border border-[#1e1e2e]"
            >
              Initialize git
            </button>
          </>
        ) : (
          <>
            <select
              value={currentBranch ?? ""}
              onChange={(e) => onSelectBranch(path, e.target.value)}
              className="px-2 py-1 rounded bg-[#12121a] border border-[#1e1e2e] text-gray-200 text-xs font-mono focus:outline-none focus:border-purple-600"
            >
              {currentBranch && !branches.includes(currentBranch) && (
                <option value={currentBranch}>{currentBranch}</option>
              )}
              {branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <span className="text-[10px] text-gray-600">{branches.length} branches</span>
            <div className="flex items-center gap-1 ml-auto">
              <input
                value={newBranch}
                onChange={(e) => setNewBranch(e.target.value)}
                placeholder="new-branch"
                className="w-28 px-2 py-1 rounded bg-[#12121a] border border-[#1e1e2e] text-gray-200 text-xs font-mono focus:outline-none focus:border-purple-600"
              />
              <button
                onClick={() => {
                  if (newBranch.trim()) {
                    onSelectBranch(path, newBranch.trim(), true);
                    setNewBranch("");
                  }
                }}
                className="px-2 py-1 text-xs rounded bg-[#1a1a24] text-gray-200 hover:bg-[#22222e] border border-[#1e1e2e]"
              >
                + Create
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
