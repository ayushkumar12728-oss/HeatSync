import React from 'react';
import { Layers, RotateCcw, X } from 'lucide-react';
import { LayerControl } from './LayerControl';

// Right sidebar: "MAP LAYERS" header + RESET ALL + the existing LayerControl
// (collapsible groups with toggles, opacity sliders and legends).
export const LayerPanel = ({
  showBuildings, setShowBuildings,
  showRoads, setShowRoads,
  showGreen, setShowGreen,
  showWater, setShowWater,
  showTrees, setShowTrees,
  availability = {},
  thematicToggles = {},
  setThematicToggle = () => {},
  opacities = {},
  setOpacity = () => {},
  showWeatherPanel = false,
  setShowWeatherPanel = () => {},
  monitoringLoading = false,
  onClose = null,
  onResetAll = null
}) => {
  const resetAll = onResetAll || (() => {
    setShowBuildings(true);
    setShowRoads(true);
    setShowGreen(true);
    setShowWater(true);
    setShowTrees(true);
    setShowWeatherPanel(true);
    Object.keys(thematicToggles).forEach((key) => setThematicToggle(key, false));
    Object.keys(opacities).forEach((key) => setOpacity(key, 80));
  });

  return (
    <>
      <div className="side-panel-header">
        <Layers size={15} color="var(--primary-sky)" />
        <strong>Map Layers</strong>
        <button className="layer-panel-reset" onClick={resetAll} title="Reset all layer toggles and opacities">
          <RotateCcw size={11} />
          Reset All
        </button>
        {onClose && (
          <button className="side-close" onClick={onClose} aria-label="Close layers" style={{ display: 'flex' }}>
            <X size={15} />
          </button>
        )}
      </div>
      <div className="side-panel-body" style={{ padding: '0 0 12px', gap: 0 }}>
        <LayerControl
          showBuildings={showBuildings}
          setShowBuildings={setShowBuildings}
          showRoads={showRoads}
          setShowRoads={setShowRoads}
          showGreen={showGreen}
          setShowGreen={setShowGreen}
          showWater={showWater}
          setShowWater={setShowWater}
          showTrees={showTrees}
          setShowTrees={setShowTrees}
          availability={availability}
          thematicToggles={thematicToggles}
          setThematicToggle={setThematicToggle}
          opacities={opacities}
          setOpacity={setOpacity}
          showWeatherPanel={showWeatherPanel}
          setShowWeatherPanel={setShowWeatherPanel}
          monitoringLoading={monitoringLoading}
        />
      </div>
    </>
  );
};

export default LayerPanel;
