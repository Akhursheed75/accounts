"use client";

import { money } from "@/lib/format";

/** A deliberately small chart drawn from the API's own numbers.
 *  There is no hard-coded series anywhere in this file. */
export function TrendChart({
  points, currency, label,
}: {
  points: { date: string; value: number }[];
  currency: string;
  label: string;
}) {
  if (points.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-ink-500">
        No {label.toLowerCase()} recorded in this period.
      </p>
    );
  }

  const width = 640;
  const height = 150;
  const padding = { top: 10, right: 8, bottom: 20, left: 8 };
  const max = Math.max(...points.map((p) => p.value), 1);
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const barWidth = Math.max(2, Math.min(28, innerWidth / points.length - 4));

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-40 w-full min-w-[420px]"
        role="img"
        aria-label={`${label} by day`}
      >
        {[0.25, 0.5, 0.75, 1].map((fraction) => (
          <line
            key={fraction}
            x1={padding.left}
            x2={width - padding.right}
            y1={padding.top + innerHeight * (1 - fraction)}
            y2={padding.top + innerHeight * (1 - fraction)}
            className="stroke-ink-200"
            strokeWidth={1}
          />
        ))}
        {points.map((point, index) => {
          const x =
            padding.left + (innerWidth / points.length) * index + (innerWidth / points.length - barWidth) / 2;
          const barHeight = (point.value / max) * innerHeight;
          return (
            <g key={point.date}>
              <rect
                x={x}
                y={padding.top + innerHeight - barHeight}
                width={barWidth}
                height={Math.max(barHeight, point.value > 0 ? 2 : 0)}
                rx={2}
                className="fill-brand-500"
                opacity={0.9}
              >
                <title>{`${point.date}: ${money(point.value, currency)}`}</title>
              </rect>
              {points.length <= 16 && (
                <text
                  x={x + barWidth / 2}
                  y={height - 6}
                  textAnchor="middle"
                  fontSize="9"
                  className="fill-ink-400"
                >
                  {point.date.slice(8)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function StatusBar({
  segments,
}: {
  segments: { label: string; value: number; className: string }[];
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  if (total === 0) {
    return <div className="h-2 w-full rounded-full bg-ink-200" />;
  }
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-ink-200">
      {segments.map((segment) => (
        <div
          key={segment.label}
          className={segment.className}
          style={{ width: `${(segment.value / total) * 100}%` }}
          title={`${segment.label}: ${segment.value}`}
        />
      ))}
    </div>
  );
}
