'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface CandlestickChartProps {
  candles: Candle[];
  height?: number;
  signalDirection?: string;
  signalPrice?: number;
  loading?: boolean;
}

// Cache the library globally — import once, reuse forever
let lwcModule: any = null;
const lwcPromise = typeof window !== 'undefined'
  ? import('lightweight-charts').then(m => { lwcModule = m; return m; })
  : null;

function ChartSkeleton({ height }: { height: number }) {
  return (
    <div className="flex items-center justify-center bg-bg-secondary rounded-lg border border-border-default" style={{ height }}>
      <div className="flex flex-col items-center gap-3">
        <div className="relative w-10 h-10">
          <div className="absolute inset-0 rounded-full border-2 border-border-default"></div>
          <div className="absolute inset-0 rounded-full border-2 border-t-accent-violet animate-spin"></div>
        </div>
        <span className="text-xs text-text-muted">Loading chart...</span>
      </div>
    </div>
  );
}

export default function CandlestickChart({
  candles, height = 400, signalDirection, signalPrice, loading = false
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const volumeSeriesRef = useRef<any>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const [libReady, setLibReady] = useState(!!lwcModule);

  // Wait for library to load (usually already cached)
  useEffect(() => {
    if (lwcModule) { setLibReady(true); return; }
    lwcPromise?.then(() => setLibReady(true));
  }, []);

  // Create chart once when library + container are ready
  const createChart = useCallback(() => {
    if (!containerRef.current || !lwcModule) return;
    if (chartRef.current) return;

    const LWC = lwcModule;
    const chart = LWC.createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: '#0F0F1E' },
        textColor: '#8888AA',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1C1C3520' },
        horzLines: { color: '#1C1C3520' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#6C63FF40', width: 1, style: 2 },
        horzLine: { color: '#6C63FF40', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: '#2A2A4A',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: '#2A2A4A',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    candleSeriesRef.current = chart.addCandlestickSeries({
      upColor: '#10B981',
      downColor: '#E94560',
      borderUpColor: '#10B981',
      borderDownColor: '#E94560',
      wickUpColor: '#10B98180',
      wickDownColor: '#E9456080',
    });

    observerRef.current = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observerRef.current.observe(containerRef.current);
  }, [height]);

  // Init chart when lib ready
  useEffect(() => {
    if (libReady) createChart();
    return () => {
      observerRef.current?.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
        volumeSeriesRef.current = null;
      }
    };
  }, [libReady, createChart]);

  // Update data without recreating chart
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    const formatted = candles.map(c => {
      let ts: number;
      if (c.time.includes('T') || c.time.includes('-')) {
        ts = Math.floor(new Date(c.time).getTime() / 1000);
      } else {
        ts = parseInt(c.time);
      }
      return { time: ts as any, open: c.open, high: c.high, low: c.low, close: c.close };
    }).sort((a: any, b: any) => a.time - b.time);

    candleSeriesRef.current.setData(formatted);

    // Volume
    if (candles.some(c => c.volume && c.volume > 0)) {
      if (!volumeSeriesRef.current && chartRef.current) {
        volumeSeriesRef.current = chartRef.current.addHistogramSeries({
          color: '#6C63FF33',
          priceFormat: { type: 'volume' },
          priceScaleId: '',
        });
        volumeSeriesRef.current.priceScale().applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
      }
      if (volumeSeriesRef.current) {
        const volData = candles.map((c, i) => ({
          time: formatted[i]?.time,
          value: c.volume || 0,
          color: c.close >= c.open ? '#10B98133' : '#E9456033',
        })).filter(v => v.time);
        volumeSeriesRef.current.setData(volData);
      }
    }

    // Signal marker
    if (signalDirection && formatted.length > 0) {
      const last = formatted[formatted.length - 1];
      candleSeriesRef.current.setMarkers([{
        time: last.time,
        position: signalDirection === 'LONG' ? 'belowBar' : 'aboveBar',
        color: signalDirection === 'LONG' ? '#10B981' : '#E94560',
        shape: signalDirection === 'LONG' ? 'arrowUp' : 'arrowDown',
        text: signalDirection,
      }]);
    } else {
      candleSeriesRef.current.setMarkers([]);
    }

    chartRef.current?.timeScale().fitContent();
  }, [candles, signalDirection, signalPrice]);

  if (!libReady || (loading && candles.length === 0)) {
    return <ChartSkeleton height={height} />;
  }

  return (
    <div className="relative">
      {loading && (
        <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5 bg-bg-secondary/80 px-2 py-1 rounded text-xs text-text-muted">
          <div className="w-3 h-3 rounded-full border border-border-default border-t-accent-violet animate-spin"></div>
          Updating...
        </div>
      )}
      <div ref={containerRef} className="rounded-lg overflow-hidden" style={{ height }} />
    </div>
  );
}
