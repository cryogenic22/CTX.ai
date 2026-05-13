/**
 * Fixture for CP-010.5 / CP-011 — TSX with realistic React patterns.
 *
 * Pins:
 *  - export default function component
 *  - generic-heavy signature
 *  - JSX inside generic-type position (CP-011 edge case)
 *  - imports from sibling components
 */

import { useState } from "react";
import { Card } from "./Card";
import { formatLabel } from "./format";
import { useFoo } from "./useFoo";

type Item<T extends { id: string }> = {
  payload: T;
  label: string;
};

export default function App<T extends { id: string }>(props: { items: Item<T>[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const foo = useFoo();

  return (
    <div className="app">
      {props.items.map((it) => (
        <Card
          key={it.payload.id}
          label={formatLabel(it.label)}
          onClick={() => setSelected(it.payload.id)}
        />
      ))}
      <pre>{selected}</pre>
      <pre>{foo}</pre>
    </div>
  );
}
