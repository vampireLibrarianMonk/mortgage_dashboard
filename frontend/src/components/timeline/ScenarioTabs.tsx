import { useState } from "react";
import type { TimelineScenario } from "../../types";

interface Props {
  scenarios: TimelineScenario[];
  active: number;
  onSelect: (index: number) => void;
  onAdd: () => void;
  onDuplicate: () => void;
  onRename: (index: number, name: string) => void;
  onDelete: (index: number) => void;
}

/**
 * Scenario tab strip for the Timeline Builder. Each tab is a named timeline plan;
 * switching tabs swaps which plan the builder edits/projects. The strip scrolls
 * horizontally when there are more tabs than fit (no hard cap). Double-click a tab
 * name to rename it. Controls: + add blank, ⧉ duplicate active, × delete.
 */
export default function ScenarioTabs({
  scenarios,
  active,
  onSelect,
  onAdd,
  onDuplicate,
  onRename,
  onDelete,
}: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");

  const startRename = (i: number) => {
    setEditing(i);
    setDraft(scenarios[i].name);
  };
  const commitRename = () => {
    if (editing === null) return;
    const name = draft.trim() || scenarios[editing].name;
    onRename(editing, name);
    setEditing(null);
  };

  return (
    <div className="scenario-tabs">
      <div className="scenario-tabs-strip" role="tablist">
        {scenarios.map((s, i) => (
          <div
            key={i}
            role="tab"
            aria-selected={i === active}
            className={i === active ? "scenario-tab active" : "scenario-tab"}
            onClick={() => onSelect(i)}
            onDoubleClick={() => startRename(i)}
            title="Click to switch · double-click to rename"
          >
            {editing === i ? (
              <input
                className="scenario-tab-edit"
                value={draft}
                autoFocus
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  if (e.key === "Escape") setEditing(null);
                }}
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="scenario-tab-name">{s.name}</span>
            )}
          </div>
        ))}
      </div>
      <div className="scenario-tab-actions">
        <button type="button" onClick={onAdd} title="New blank scenario">
          +
        </button>
        <button type="button" onClick={onDuplicate} title="Duplicate the current scenario">
          ⧉
        </button>
        <button
          type="button"
          onClick={() => onDelete(active)}
          disabled={scenarios.length <= 1}
          title={scenarios.length <= 1 ? "Can't delete the only scenario" : "Delete the current scenario"}
        >
          ×
        </button>
      </div>
    </div>
  );
}
