export class GanttRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    this.canvas.width = this.canvas.clientWidth;
  }

  render(snapshot) {
    const ctx = this.ctx;
    const width = this.canvas.width;
    const height = this.canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#06111c";
    ctx.fillRect(0, 0, width, height);
    const now = new Date(snapshot.timestamp).getTime();
    const start = now - 6 * 3600 * 1000;
    const end = now + 6 * 3600 * 1000;
    const contentWidth = width - 150;
    const rows = snapshot.satellites.slice(0, 16);
    const rowHeight = Math.max(18, Math.floor((height - 42) / Math.max(rows.length, 1)));
    for (let hour = 0; hour <= 12; hour += 1) {
      const x = 140 + (hour / 12) * contentWidth;
      ctx.strokeStyle = "rgba(255,255,255,0.08)";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    rows.forEach((sat, row) => {
      const y = 28 + row * rowHeight;
      ctx.fillStyle = "#84a5c6";
      ctx.font = "11px IBM Plex Mono";
      ctx.fillText(sat.id, 8, y + 10);
      ctx.fillStyle = "rgba(95,240,178,0.1)";
      ctx.fillRect(140, y, contentWidth, rowHeight - 4);
      sat.maneuver_queue.forEach((maneuver) => {
        const burn = new Date(maneuver.burnTime).getTime();
        const x = 140 + ((burn - start) / (end - start)) * contentWidth;
        const widthBlock = Math.max(10, contentWidth * (600000 / (end - start)));
        const primaryColor = maneuver.maneuver_type === "EVASION" ? "#ffbe55" : "#60c4ff";
        ctx.fillStyle = primaryColor;
        ctx.fillRect(x, y + 2, widthBlock, rowHeight - 8);
        ctx.fillStyle = "rgba(255,95,114,0.45)";
        ctx.fillRect(x + widthBlock, y + 2, widthBlock * 0.9, rowHeight - 8);
        ctx.fillStyle = "#021019";
        ctx.fillText(maneuver.burn_id.slice(0, 10), x + 2, y + 12);
      });
      if (!sat.maneuver_queue.length && sat.status === "RECOVERING") {
        ctx.fillStyle = "rgba(96,196,255,0.24)";
        ctx.fillRect(160, y + 2, 120, rowHeight - 8);
      }
    });
    const nowX = 140 + ((now - start) / (end - start)) * contentWidth;
    ctx.strokeStyle = "#ff5f72";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(nowX, 0);
    ctx.lineTo(nowX, height);
    ctx.stroke();
  }
}
