export class HeatmapRenderer {
  constructor(root, chartCanvas) {
    this.root = root;
    this.chart = new Chart(chartCanvas.getContext("2d"), {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Cumulative Delta-V (m/s)",
            yAxisID: "y",
            data: [],
            borderColor: "#60c4ff",
            backgroundColor: "rgba(96,196,255,0.16)",
            fill: true,
            tension: 0.35,
          },
          {
            label: "Avoided Events",
            yAxisID: "y1",
            data: [],
            borderColor: "#5ff0b2",
            backgroundColor: "rgba(95,240,178,0.1)",
            tension: 0.35,
          },
        ],
      },
      options: {
        responsive: true,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { position: "left", ticks: { color: "#84a5c6" }, grid: { color: "rgba(255,255,255,0.08)" } },
          y1: { position: "right", ticks: { color: "#84a5c6" }, grid: { drawOnChartArea: false } },
          x: { ticks: { color: "#84a5c6", maxTicksLimit: 6 }, grid: { color: "rgba(255,255,255,0.04)" } },
        },
        plugins: {
          legend: { labels: { color: "#e6f3ff" } },
        },
      },
    });
  }

  render(snapshot) {
    this.root.innerHTML = "";
    const grid = document.createElement("div");
    grid.className = "heatmap-grid";
    const ordered = [...snapshot.satellites].sort((a, b) => b.active_cdms - a.active_cdms || a.fuel_kg - b.fuel_kg);
    ordered.forEach((sat) => {
      const fuelPct = Math.max(0, Math.min(100, (sat.fuel_kg / 50) * 100));
      const color = fuelPct > 50 ? "#5ff0b2" : fuelPct > 20 ? "#ffbe55" : "#ff5f72";
      const card = document.createElement("div");
      card.className = "fuel-card";
      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
          <div>
            <strong>${sat.id}</strong>
            <div class="tiny">${sat.active_cdms} active CDMs</div>
          </div>
          <span class="status-badge" style="background:${color}22;color:${color};">${sat.status}</span>
        </div>
        <div class="fuel-bar"><div class="fuel-fill" style="width:${fuelPct}%;background:${color};color:${color};"></div></div>
        <div class="tiny" style="margin-top:10px;">Fuel ${sat.fuel_kg.toFixed(2)} kg</div>
        <div class="tiny">${sat.is_demo ? "Seeded threat corridor active" : "Routine constellation slot"}</div>
      `;
      grid.appendChild(card);
    });
    this.root.appendChild(grid);
    this.chart.data.labels = snapshot.metrics.map((entry) => new Date(entry.timestamp).toLocaleTimeString());
    this.chart.data.datasets[0].data = snapshot.metrics.map((entry) => entry.cumulative_delta_v_mps);
    this.chart.data.datasets[1].data = snapshot.metrics.map((entry) => entry.collisions_avoided);
    this.chart.update("none");
  }
}
