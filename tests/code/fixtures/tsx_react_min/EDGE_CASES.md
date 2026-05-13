# tsx_react_min — edge cases pinned

Fixture for CP-010.5 / CP-011 / CP-012 / CP-013 / CP-015. Each file
pins what one of these tasks must handle.

| File | Element | Pins |
|---|---|---|
| App.tsx | `export default function App<T extends ...>(...)` | Default-exported function component with generic-heavy signature |
| App.tsx | `<Card key={...} label={...} />` | JSX usage edge (CP-015 component-usage call graph) |
| App.tsx | `useState<string \| null>(null)` | Hook detection inside JSX-heavy context (CP-013) |
| Card.tsx | `forwardRef<HTMLDivElement, CardProps>(...)` | forwardRef component recognition (CP-012) |
| Card.tsx | `useState/useEffect/useMemo` | Multiple hooks per component (CP-013) |
| Card.tsx | `interface CardProps` | TS interface treated as a `type` kind, not a component |
| useFoo.ts | `function useFoo(): string` | Custom hook (named with `use` prefix, calls hooks internally) |
| useFoo.ts | `function notAHook()` | Plain utility — NOT classified as a hook |
| format.ts | `export type LabelStyle = …` | Type alias as a separate symbol kind |
| format.ts | `export const SEPARATOR = " | "` | Exported constant — separate from functions |
| format.ts | `function privateHelper(…)` | Non-exported utility — surfaces but flagged unexported |

Total expected symbols across the fixture (function components +
exported utilities + types + hooks):

  App.tsx     -> App (component), Item (type)
  Card.tsx    -> Card (component), CardProps (type)
  useFoo.ts   -> useFoo (hook), notAHook (function)
  format.ts   -> formatLabel (function), LabelStyle (type), SEPARATOR (const), privateHelper (function)

= 10 symbols total at CP-012 + 4 hook attachments at CP-013.
