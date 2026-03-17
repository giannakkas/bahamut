'use client';

import { useEffect, useRef, useState } from 'react';

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
  indicators?: {
    ema_20?: number;
    ema_50?: number;
    ema_200?: number;
  };
  signalDirection?: string;
  signalPrice?: number;
}

export default function CandlestickChart({
  candles, height = 400, indicators, signalDirection, signalPrice
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    let chart: any;

    const initChart = async () => {
      try {
        const LWC = await import('lightweight-charts');

        // Clear previous chart
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
        containerRef.current!.innerHTML = '';

        chart = LWC.createChart(containerRef.current!, {
          width: containerRef.current!.clientWidth,
          height: height,
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

        // Candlestick series
        const candleSeries = chart.addCandlestickSeries({
          upColor: '#10B981',
          downColor: '#E94560',
          borderUpColor: '#10B981',
          borderDownColor: '#E94560',
          wickUpColor: '#10B98180',
          wickDownColor: '#E9456080',
        });

        // Format candle data
        const formattedCandles = candles.map(c => {
          let ts: number;
          if (c.time.includes('T') || c.time.includes('-')) {
            ts = Math.floor(new Date(c.time).getTime() / 1000);
          } else {
            ts = parseInt(c.time);
          }
          return { time: ts as any, open: c.open, high: c.high, low: c.low, close: c.close };
        }).sort((a: any, b: any) => a.time - b.time);

        candleSeries.setData(formattedCandles);

        // Volume series
        if (candles.some(c => c.volume && c.volume > 0)) {
          const volumeSeries = chart.addHistogramSeries({
            color: '#6C63FF33',
            priceFormat: { type: 'volume' },
            priceScaleId: '',
          });
          volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
          });

          const volData = candles.map((c, i) => ({
            time: formattedCandles[i]?.time,
            value: c.volume || 0,
            color: c.close >= c.open ? '#10B98133' : '#E9456033',
          })).filter(v => v.time);

          volumeSeries.setData(volData);
        }

        // Signal marker
        if (signalDirection && signalPrice && formattedCandles.length > 0) {
          const lastCandle = formattedCandles[formattedCandles.length - 1];
          candleSeries.setMarkers([{
            time: lastCandle.time,
            position: signalDirection === 'LONG' ? 'belowBar' : 'aboveBar',
            color: signalDirection === 'LONG' ? '#10B981' : '#E94560',
            shape: signalDirection === 'LONG' ? 'arrowUp' : 'arrowDown',
            text: signalDirection,
          }]);
        }

        // Fit content
        chart.timeScale().fitContent();
        setLoaded(true);

        // Resize observer
        const observer = new ResizeObserver(() => {
          if (containerRef.current && chart) {
            chart.applyOptions({ width: containerRef.current.clientWidth });
          }
        });
        observer.observe(containerRef.current!);

        return () => observer.disconnect();
      } catch (e) {
        console.error('Chart init error:', e);
      }
    };

    initChart();

    return () => {
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [candles, height, signalDirection, signalPrice]);

  return (
    <div className="relative">
      {!loaded && candles.length > 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-bg-secondary z-10">
          <span className="text-sm text-text-muted">Loading chart...</span>
        </div>
      )}
      {candles.length === 0 && (
        <div className="flex items-center justify-center bg-bg-secondary rounded-lg border border-border-default" style={{ height }}>
          <span className="text-sm text-text-muted">No candle data available</span>
        </div>
      )}
      <div ref={containerRef} className="rounded-lg overflow-hidden" style={{ height: candles.length > 0 ? height : 0 }} />
    </div>
  );
}
