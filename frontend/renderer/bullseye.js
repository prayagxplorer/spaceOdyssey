export class BullseyeRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    this.canvas.width = this.canvas.clientWidth;
  }

  riskColor(risk) {
    if (risk === "RED") return "#ff5f72";
    if (risk === "YELLOW") return "#ffbe55";
    return "#52f6ff";
  }

  render(conjunctions, selectedId) {
    const ctx = this.ctx;
    const { width, height } = this.canvas;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.38;
    ctx.clearRect(0, 0, width, height);
    const gradient = ctx.createRadialGradient(cx, cy, 20, cx, cy, radius * 1.2);
    gradient.addColorStop(0, "rgba(82,246,255,0.08)");
    gradient.addColorStop(1, "rgba(2,6,13,1)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(96,196,255,0.16)";
    ctx.lineWidth = 1;
    for (let ring = 1; ring <= 4; ring += 1) {
      ctx.beginPath();
      ctx.arc(cx, cy, (radius / 4) * ring, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(96,196,255,0.25)";
    ctx.beginPath();
    ctx.moveTo(cx, cy - radius);
    ctx.lineTo(cx, cy + radius);
    ctx.moveTo(cx - radius, cy);
    ctx.lineTo(cx + radius, cy);
    ctx.stroke();
    ctx.fillStyle = "#84a5c6";
    ctx.font = "12px IBM Plex Mono";
    ctx.fillText("24h", cx + radius - 26, cy + 14);
    ctx.fillText("0h", cx + 10, cy + 18);
    if (!selectedId) {
      ctx.fillStyle = "#84a5c6";
      ctx.fillText("Select a satellite on the map", cx - 92, cy);
      return;
    }
    const relevant = conjunctions.filter((item) => item.sat_id === selectedId);
    relevant.forEach((item, index) => {
      const vector = item.approach_vector || [1, 0];
      const angle = Math.atan2(vector[1], vector[0]);
      const radial = (Math.min(item.tca_seconds, 86400) / 86400) * radius;
      const x = cx + Math.cos(angle) * radial;
      const y = cy + Math.sin(angle) * radial;
      const color = this.riskColor(item.risk);
      ctx.strokeStyle = color;
      ctx.lineWidth = item.is_demo ? 3 : 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, item.is_demo ? 6 : 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 0.18;
      ctx.beginPath();
      ctx.arc(x, y, 14 + index * 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    });
  }
}
