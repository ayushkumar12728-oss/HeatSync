import React from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';
import { Clock, BarChart2, Wind, Activity } from 'lucide-react';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

export default function RealtimeCharts({ liveWeather }) {
  const currentTemp = liveWeather?.temperature_c ?? 34.8;

  // 24-Hour Diurnal Microclimate Curve scaled to current temperature
  const diurnalLabels = [
    '00:00', '02:00', '04:00', '06:00', '08:00', '10:00',
    '12:00', '14:00', '16:00', '18:00', '20:00', '22:00'
  ];

  const diurnalData = {
    labels: diurnalLabels,
    datasets: [
      {
        label: 'Urban Surface LST (°C)',
        data: [27.2, 26.1, 25.4, 28.5, 33.1, Math.max(36.0, currentTemp + 2.5), 41.8, 43.5, 39.2, 34.0, 30.5, 28.8],
        borderColor: '#f43f5e',
        backgroundColor: 'rgba(244, 63, 94, 0.14)',
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#f43f5e',
        pointBorderColor: '#ffffff',
        pointHoverRadius: 6,
      },
      {
        label: 'Ambient Air Temp (°C)',
        data: [26.0, 25.2, 24.8, 26.5, 30.0, currentTemp, 36.5, 38.0, 35.2, 31.8, 29.0, 27.5],
        borderColor: '#38bdf8',
        backgroundColor: 'rgba(56, 189, 248, 0.12)',
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#38bdf8',
        pointBorderColor: '#ffffff',
        pointHoverRadius: 6,
      },
      {
        label: 'Shaded Green Corridor (°C)',
        data: [25.0, 24.5, 24.0, 25.2, 27.8, Math.max(29.0, currentTemp - 3.8), 32.1, 33.4, 31.5, 29.0, 27.0, 26.0],
        borderColor: '#34d399',
        backgroundColor: 'rgba(52, 211, 153, 0.15)',
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#34d399',
        pointBorderColor: '#ffffff',
        pointHoverRadius: 6,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: '#e2e8f0',
          font: { family: 'Inter', size: 11, weight: '700' },
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(3, 9, 30, 0.95)',
        titleColor: '#34d399',
        bodyColor: '#f1f5f9',
        borderColor: 'rgba(52, 211, 153, 0.3)',
        borderWidth: 1,
        padding: 12,
        cornerRadius: 14,
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255, 255, 255, 0.05)' },
        ticks: { color: '#94a3b8', font: { size: 10 } },
      },
      y: {
        grid: { color: 'rgba(255, 255, 255, 0.05)' },
        ticks: { color: '#94a3b8', font: { size: 10 } },
      },
    },
  };

  // 53,802 Grid Cell LST Frequency Distribution
  const histogramData = {
    labels: ['< 30°C', '30-33°C', '33-36°C', '36-39°C', '39-42°C', '42-45°C', '> 45°C'],
    datasets: [
      {
        label: 'Grid Cell Count (100m Lattice)',
        data: [3240, 9420, 18650, 14210, 6120, 1840, 322],
        backgroundColor: [
          'rgba(52, 211, 153, 0.85)',
          'rgba(45, 212, 191, 0.85)',
          'rgba(56, 189, 248, 0.85)',
          'rgba(251, 191, 36, 0.85)',
          'rgba(249, 115, 22, 0.85)',
          'rgba(244, 63, 94, 0.85)',
          'rgba(159, 18, 57, 0.95)',
        ],
        borderRadius: 8,
        borderWidth: 1,
        borderColor: 'rgba(255, 255, 255, 0.2)',
      },
    ],
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      
      {/* 24-Hour Diurnal Microclimate Curve */}
      <div className="p-6 rounded-3xl liquid-glass space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
            <h3 className="text-sm font-extrabold text-white tracking-wide uppercase">
              24-Hour Diurnal Microclimate Cycle
            </h3>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-950/90 text-emerald-300 border border-emerald-500/40 font-bold">
            Live Dynamic Feed
          </span>
        </div>

        <div className="h-64 w-full">
          <Line data={diurnalData} options={chartOptions} />
        </div>
      </div>

      {/* 53,802 Grid Cell LST Frequency Distribution */}
      <div className="p-6 rounded-3xl liquid-glass space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart2 className="w-4 h-4 text-teal-400 drop-shadow-[0_0_8px_rgba(45,212,191,0.7)]" />
            <h3 className="text-sm font-extrabold text-white tracking-wide uppercase">
              53,802 Cell LST Frequency Distribution
            </h3>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-teal-950/90 text-teal-300 border border-teal-500/40 font-bold">
            100m Resolution
          </span>
        </div>

        <div className="h-64 w-full">
          <Bar data={histogramData} options={chartOptions} />
        </div>
      </div>

    </div>
  );
}
