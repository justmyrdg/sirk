(() => {
  "use strict";

  if (!window.Chart) return;

  // Colors come from CSS custom properties so the palette lives in one place.
  const css = getComputedStyle(document.documentElement);
  const token = (name, fallback) => (css.getPropertyValue(name) || "").trim() || fallback;
  const palette = [token("--chart-1", "#2a78d6"), token("--chart-2", "#f15a24")];
  const ink = token("--ink", "#242124");
  const muted = token("--muted", "#697487");
  const grid = token("--line", "#e4eaf2");
  const surface = "#ffffff";

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthLabel = key => {
    const [year, month] = String(key).split("-");
    return month ? `${MONTHS[Number(month) - 1]} ${year.slice(2)}` : String(key);
  };
  const peso = value => `₱${Number(value || 0).toLocaleString("en-PH", { maximumFractionDigits: 2 })}`;
  const formatter = format => (format === "peso" ? peso : value => Number(value || 0).toLocaleString("en-PH"));

  Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.color = muted;

  // Draws a low–high whisker on each projected point (one axis, no fill).
  const rangePlugin = {
    id: "fipRange",
    afterDatasetsDraw(chart, _args, options) {
      const range = options && options.range;
      if (!range) return;
      const { ctx, scales } = chart;
      const meta = chart.getDatasetMeta(1);
      ctx.save();
      ctx.strokeStyle = palette[1];
      ctx.lineWidth = 2;
      meta.data.forEach((point, index) => {
        if (index < range.from) return;
        const top = scales.y.getPixelForValue(range.high);
        const bottom = scales.y.getPixelForValue(range.low);
        ctx.beginPath();
        ctx.moveTo(point.x, top);
        ctx.lineTo(point.x, bottom);
        ctx.moveTo(point.x - 5, top);
        ctx.lineTo(point.x + 5, top);
        ctx.moveTo(point.x - 5, bottom);
        ctx.lineTo(point.x + 5, bottom);
        ctx.stroke();
      });
      ctx.restore();
    }
  };

  function dataset(series, index, kind) {
    const color = palette[index % palette.length];
    const base = { label: series.name, data: series.values, borderColor: color, backgroundColor: color };
    if (kind === "line" || kind === "forecast") {
      const projected = kind === "forecast" && index === 1;
      return {
        ...base,
        type: "line",
        borderWidth: 2,
        borderDash: projected ? [5, 4] : [],
        pointRadius: projected ? 5 : 4,
        pointHoverRadius: 6,
        pointBorderColor: surface,
        pointBorderWidth: 2,
        tension: 0,
        spanGaps: false
      };
    }
    return {
      ...base,
      type: "bar",
      borderWidth: 0,
      borderRadius: 4,
      borderSkipped: "start",
      maxBarThickness: 28,
      categoryPercentage: 0.7,
      barPercentage: 0.9
    };
  }

  function draw(canvas) {
    const block = document.getElementById(`chart-data-${canvas.dataset.chart}`);
    if (!block) return;
    let spec;
    try {
      spec = JSON.parse(block.textContent);
    } catch (error) {
      return;
    }
    const format = formatter(spec.format);
    const horizontal = spec.kind === "hbar";
    const isMonth = spec.labelFormat !== "item";
    const labels = spec.labels.map(label => (isMonth ? monthLabel(label) : label));
    const valueAxis = {
      beginAtZero: true,
      grid: { color: grid, drawTicks: false },
      border: { display: false },
      ticks: { color: muted, padding: 6, precision: spec.format === "count" ? 0 : undefined, callback: value => format(value) }
    };
    const categoryAxis = {
      grid: { display: false },
      border: { color: grid },
      ticks: { color: muted, maxRotation: 0, autoSkip: true, autoSkipPadding: 8 }
    };

    new Chart(canvas, {
      type: spec.kind === "line" || spec.kind === "forecast" ? "line" : "bar",
      data: { labels, datasets: spec.series.map((series, index) => dataset(series, index, spec.kind)) },
      options: {
        indexAxis: horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
        plugins: {
          legend: {
            display: spec.series.length > 1,
            position: "top",
            align: "start",
            labels: { color: ink, boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "rectRounded" }
          },
          tooltip: {
            backgroundColor: ink,
            titleColor: "#ffffff",
            bodyColor: "#ffffff",
            padding: 10,
            cornerRadius: 6,
            filter: item => item.raw !== null && item.raw !== undefined,
            callbacks: {
              label: item => {
                let text = `${item.dataset.label}: ${format(item.raw)}`;
                if (spec.range && item.datasetIndex === 1) text += ` (likely ${format(spec.range.low)}–${format(spec.range.high)})`;
                return text;
              }
            }
          },
          fipRange: { range: spec.range || null }
        }
      },
      plugins: [rangePlugin]
    });
  }

  document.querySelectorAll("canvas[data-chart]").forEach(draw);
})();
