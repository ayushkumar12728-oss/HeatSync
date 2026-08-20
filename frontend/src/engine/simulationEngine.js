// Simulation & Microclimate Physics Engine for HeatSync
// Calculates "what-if" intervention scenarios, uncertainty bounds, and equity benefit scores.

/**
 * Runs a microclimate simulation across grid cells for given intervention parameters.
 * 
 * @param {Array} gridCells - Array of baseline grid cell objects
 * @param {Object} scenario - Interventions payload { treeCanopyAdd, coolRoofAdd, shadeAdd, trafficReduce, selectedCellIds }
 * @returns {Object} Simulation results including mutated cells, deltas, uncertainty bands, and ranking
 */
export const runInterventionSimulation = (gridCells, scenario) => {
  const {
    treeCanopyAdd = 0,     // % additional canopy (0 to 50%)
    coolRoofAdd = 0,       // % additional cool roofs (0 to 70%)
    shadeAdd = 0,          // % shade structures (0 to 40%)
    trafficReduce = 0,     // % traffic reduction (0 to 80%)
    selectedCellIds = null // null means global apply, or array of specific cell IDs
  } = scenario;

  let totalTempDropSum = 0;
  let totalAQIDropSum = 0;
  let totalVulnerablePopShielded = 0;

  const simulatedCells = gridCells.map(cell => {
    const isTargeted = !selectedCellIds || selectedCellIds.length === 0 || selectedCellIds.includes(cell.id);

    if (!isTargeted) {
      return {
        ...cell,
        simulatedLST: cell.baselineLST,
        simulatedAQI: cell.baselineAQI,
        tempDelta: 0,
        aqiDelta: 0,
        benefitScore: 0,
        confidenceLowerLST: cell.baselineLST - (cell.uncertaintyScore * 0.03),
        confidenceUpperLST: cell.baselineLST + (cell.uncertaintyScore * 0.03),
        confidenceLowerAQI: Math.max(0, cell.baselineAQI - (cell.uncertaintyScore * 0.8)),
        confidenceUpperAQI: cell.baselineAQI + (cell.uncertaintyScore * 0.8)
      };
    }

    // 1. Tree Canopy Microclimate Cooling Effect
    // Peer-reviewed coefficient: Each 10% canopy increase yields ~0.8°C to 1.8°C cooling depending on building density & albedo
    const treeCooling = (treeCanopyAdd / 10) * 1.15 * (1 - cell.ndvi * 0.5);
    const treeAQIClean = (treeCanopyAdd / 10) * 4.2;

    // 2. Cool Reflective Roof Effect
    // Each 10% cool roof conversion reduces surface LST by ~1.2°C to 2.8°C on high-density concrete roofs
    const coolRoofCooling = (coolRoofAdd / 10) * 1.45 * cell.buildingDensity;

    // 3. Shade Structure Solar Radiation Relief
    const shadeCooling = (shadeAdd / 10) * 0.85 * cell.svf;

    // 4. Traffic Rerouting & Emission Reduction Effect
    const trafficAQIClean = (trafficReduce / 10) * 7.8 * cell.trafficDensity;
    const trafficTempDrop = (trafficReduce / 10) * 0.25 * cell.trafficDensity; // reduced waste heat

    // Combined temperature & AQI reductions
    const tempDelta = Math.min(6.5, Math.round((treeCooling + coolRoofCooling + shadeCooling + trafficTempDrop) * 10) / 10);
    const aqiDelta = Math.min(120, Math.round(treeAQIClean + trafficAQIClean));

    const simulatedLST = Math.round((cell.baselineLST - tempDelta) * 10) / 10;
    const simulatedAQI = Math.max(25, Math.round(cell.baselineAQI - aqiDelta));

    // Uncertainty propagation (lower confidence = wider prediction interval bounds)
    const lstMarginOfError = Math.round((0.4 + (cell.uncertaintyScore / 100) * 1.8) * 10) / 10;
    const aqiMarginOfError = Math.round(5 + (cell.uncertaintyScore / 100) * 25);

    // Vulnerability-Weighted Equity Benefit Score
    // Prioritizes cells with high temperature/AQI drop AND high vulnerability index / outdoor worker counts
    const vulnerabilityMultiplier = 1 + (cell.vulnerabilityScore / 35) + (cell.outdoorWorkerCount / 600);
    const rawImpact = (tempDelta * 18) + (aqiDelta * 0.65);
    const benefitScore = Math.round(rawImpact * vulnerabilityMultiplier);

    if (tempDelta > 0.5 || aqiDelta > 5) {
      totalVulnerablePopShielded += Math.round((cell.popDensityKm2 * 0.01) * (cell.vulnerabilityScore / 100));
    }

    totalTempDropSum += tempDelta;
    totalAQIDropSum += aqiDelta;

    return {
      ...cell,
      appliedInterventions: {
        treeCanopyAdd,
        coolRoofAdd,
        shadeAdd,
        trafficReduce
      },
      simulatedLST,
      simulatedAQI,
      tempDelta,
      aqiDelta,
      benefitScore,
      confidenceLowerLST: Math.round((simulatedLST - lstMarginOfError) * 10) / 10,
      confidenceUpperLST: Math.round((simulatedLST + lstMarginOfError) * 10) / 10,
      confidenceLowerAQI: Math.max(0, simulatedAQI - aqiMarginOfError),
      confidenceUpperAQI: simulatedAQI + aqiMarginOfError
    };
  });

  // Calculate top priority intervention street blocks
  const rankedPriorityCells = [...simulatedCells]
    .sort((a, b) => b.benefitScore - a.benefitScore)
    .slice(0, 8);

  const affectedCellsCount = simulatedCells.filter(c => c.tempDelta > 0 || c.aqiDelta > 0).length;
  const avgTempDrop = affectedCellsCount > 0 ? Math.round((totalTempDropSum / affectedCellsCount) * 10) / 10 : 0;
  const avgAQIDrop = affectedCellsCount > 0 ? Math.round(totalAQIDropSum / affectedCellsCount) : 0;

  return {
    simulatedCells,
    rankedPriorityCells,
    summary: {
      affectedCellsCount,
      avgTempDrop,
      avgAQIDrop,
      totalVulnerablePopShielded,
      totalEquityBenefitScore: simulatedCells.reduce((acc, c) => acc + c.benefitScore, 0),
      maxSingleCellCooling: Math.max(...simulatedCells.map(c => c.tempDelta)),
      maxSingleCellAQIClean: Math.max(...simulatedCells.map(c => c.aqiDelta))
    }
  };
};
