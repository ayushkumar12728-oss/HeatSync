import React from 'react';

// Reusable thematic legend.
//   type: 'continuous' | 'categorical'
//   continuous: gradient bar with min/max labels
//   categorical: colour swatches with labels
// Every legend shows its data source + date/note when provided.
export const Legend = ({
  title,
  type = 'categorical',
  stops = [],
  min,
  max,
  unit = '',
  source,
  date,
  note,
  compact = false,
  className = ''
}) => {
  if (!stops || stops.length === 0) return null;

  return (
    <div className={`legend ${compact ? 'legend-compact' : ''} ${className}`}>
      {title && (
        <div className="legend-title">
          <strong>{title}</strong>
          {unit && <span className="legend-unit">{unit}</span>}
        </div>
      )}

      {type === 'continuous' && stops.length >= 2 ? (
        <div className="legend-continuous">
          <div
            className="legend-gradient"
            style={{
              background: `linear-gradient(90deg, ${stops.map((s) => s.color).join(', ')})`
            }}
          />
          <div className="legend-scale">
            <span>{min !== undefined ? `${min}${unit ? ` ${unit}` : ''}` : stops[0]?.value || ''}</span>
            <span>{max !== undefined ? `${max}${unit ? ` ${unit}` : ''}` : stops[stops.length - 1]?.value || ''}</span>
          </div>
        </div>
      ) : (
        <div className="legend-stops">
          {stops.map((stop, i) => (
            <div className="legend-stop" key={`${stop.label}-${i}`}>
              <span className="legend-swatch" style={{ background: stop.color }} />
              <span className="legend-stop-label">{stop.label}</span>
              {stop.value && <span className="legend-stop-value">{stop.value}</span>}
            </div>
          ))}
        </div>
      )}

      {(source || date || note) && (
        <div className="legend-meta">
          {source && <span>Source: {source}</span>}
          {date && <span>Date: {date}</span>}
          {note && <span className="legend-note">{note}</span>}
        </div>
      )}
    </div>
  );
};

export default Legend;
