/**
 * Card: function-component declaration shape with React.forwardRef.
 * Pins decorator-free component detection (CP-012) + hooks (CP-013).
 */

import { forwardRef, useEffect, useMemo, useState } from "react";

export interface CardProps {
  label: string;
  onClick?: () => void;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { label, onClick },
  ref,
) {
  const [hover, setHover] = useState(false);
  const cls = useMemo(() => (hover ? "card hover" : "card"), [hover]);

  useEffect(() => {
    if (!onClick) return;
    return () => {
      // cleanup placeholder
    };
  }, [onClick]);

  return (
    <div
      ref={ref}
      className={cls}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onClick}
    >
      {label}
    </div>
  );
});
