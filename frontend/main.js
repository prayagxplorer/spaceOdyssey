import { fetchSnapshot, stepSimulation } from "./api/client.js?v=3";
import { GroundTrackRenderer } from "./renderer/groundtrack.js?v=3";
import { BullseyeRenderer } from "./renderer/bullseye.js?v=3";
import { HeatmapRenderer } from "./renderer/heatmap.js?v=3";
import { GanttRenderer } from "./renderer/gantt.js?v=3";

const mapRenderer = new GroundTrackRenderer(document.getElementById("map-canvas"));
const bullseyeRenderer = new BullseyeRenderer(document.getElementById("bullseye"));
const heatmapRenderer = new HeatmapRenderer(
  document.getElementById("heatmap"),
  document.getElementById("efficiency-chart")
);
const ganttRenderer = new GanttRenderer(document.getElementById("gantt"));

let snapshotState = null;
let selectedSatelliteId = null;
let dirty = false;
let autoPlay = true;
let stepSeconds = 120;
let stepping = false;

window.selectSatellite = (id) => {
  selectedSatelliteId = id;
  mapRenderer.selectedId = id;
  dirty = true;
};

function riskSummary(snapshot) {
  const red = snapshot.active_conjunctions.filter((item) => item.risk === "RED").length;
  const yellow = snapshot.active_conjunctions.filter((item) => item.risk === "YELLOW").length;
  return { red, yellow };
}

function colorForRisk(risk) {
  if (risk === "RED") return "#ff5f72";
  if (risk === "YELLOW") return "#ffbe55";
  return "#52f6ff";
}

function renderTicker(snapshot) {
  const ticker = document.getElementById("incident-ticker");
  const items = [
    ...snapshot.active_conjunctions.slice(0, 8).map(
      (item) =>
        `${item.risk} threat ${item.sat_id} vs ${item.deb_id} TCA ${(item.tca_seconds / 60).toFixed(1)}m miss ${item.miss_distance_km.toFixed(3)}km`
    ),
    ...snapshot.recent_maneuvers.slice(0, 8).map(
      (item) =>
        `${item.maneuver_type} burn ${item.satellite_id} delta-v ${Number(item.delta_v_mps || 0).toFixed(2)} m/s`
    ),
  ];
  ticker.textContent = items.length ? `${items.join("    //    ")}    //    ${items.join("    //    ")}` : "No active incidents yet";
}

function renderEventFeed(snapshot) {
  const feed = document.getElementById("event-feed");
  const eventCards = [
    ...snapshot.active_conjunctions.slice(0, 6).map((item) => ({
      title: `${item.risk} conjunction corridor`,
      body: `${item.sat_id} could intersect ${item.deb_id} in ${(item.tca_seconds / 60).toFixed(1)} minutes. Miss distance ${item.miss_distance_km.toFixed(3)} km.`,
      color: colorForRisk(item.risk),
      satId: item.sat_id,
    })),
    ...snapshot.recent_maneuvers.slice(0, 6).map((item) => ({
      title: `${item.maneuver_type} burn executed`,
      body: `${item.satellite_id} ${item.event} burn ${item.burn_id} with delta-v ${Number(item.delta_v_mps || 0).toFixed(2)} m/s.`,
      color: item.maneuver_type === "EVASION" ? "#ffbe55" : "#60c4ff",
      satId: item.satellite_id,
    })),
    ...snapshot.recent_collisions.slice(0, 3).map((item) => ({
      title: `Collision event`,
      body: `${item.satellite_id} intersected ${item.debris_id} at miss distance ${item.miss_distance_km.toFixed(4)} km.`,
      color: "#ff5f72",
      satId: item.satellite_id,
    })),
  ];
  feed.innerHTML = eventCards
    .map(
      (item) => `
      <div class="feed-card" style="cursor: pointer; border-color:${item.color}40;" onclick="window.selectSatellite('${item.satId}')">
        <div style="display:flex;justify-content:space-between;gap:10px;">
          <strong style="color:${item.color};">${item.title}</strong>
        </div>
        <div class="tiny" style="margin-top:8px;">${item.body}</div>
      </div>
    `
    )
    .join("");
}

function renderDetails(snapshot) {
  const title = document.getElementById("detail-title");
  const subtitle = document.getElementById("detail-subtitle");
  const grid = document.getElementById("detail-grid");
  const alerts = document.getElementById("detail-alerts");
  if (!selectedSatelliteId) {
    const summary = riskSummary(snapshot);
    title.textContent = "Fleet Overview";
    subtitle.textContent = `${snapshot.satellites.length} satellites tracking ${snapshot.debris_cloud.length} debris objects`;
    grid.innerHTML = `
      <div>Active CDMs</div><div>${snapshot.active_conjunctions.length}</div>
      <div>RED threats</div><div>${summary.red}</div>
      <div>YELLOW threats</div><div>${summary.yellow}</div>
      <div>Queued Burns</div><div>${snapshot.satellites.reduce((sum, sat) => sum + sat.maneuver_queue.length, 0)}</div>
      <div>Recent Maneuvers</div><div>${snapshot.recent_maneuvers.length}</div>
      <div>Recent Collisions</div><div>${snapshot.recent_collisions.length}</div>
    `;
    alerts.innerHTML = snapshot.active_conjunctions.slice(0, 3).map((item) => `
      <div class="alert-chip" style="cursor: pointer; background:${colorForRisk(item.risk)}15;color:${colorForRisk(item.risk)};" onclick="window.selectSatellite('${item.sat_id}')">
        ${item.sat_id} threat corridor to ${item.deb_id} in ${(item.tca_seconds / 60).toFixed(1)}m
      </div>
    `).join("");
    return;
  }
  const sat = snapshot.satellites.find((item) => item.id === selectedSatelliteId);
  if (!sat) return;
  const satCdms = snapshot.active_conjunctions.filter((item) => item.sat_id === selectedSatelliteId);
  const satManeuvers = snapshot.recent_maneuvers.filter((item) => item.satellite_id === selectedSatelliteId);
  title.textContent = sat.id;
  subtitle.textContent = `${sat.status} | ${satCdms.length} threat tracks | fuel ${sat.fuel_kg.toFixed(2)} kg`;
  grid.innerHTML = `
    <div>Status</div><div>${sat.status}</div>
    <div>Latitude</div><div>${sat.lat.toFixed(2)} deg</div>
    <div>Longitude</div><div>${sat.lon.toFixed(2)} deg</div>
    <div>Altitude</div><div>${sat.alt_km.toFixed(2)} km</div>
    <div>Queued Burns</div><div>${sat.maneuver_queue.length}</div>
    <div>Threat Corridors</div><div>${sat.active_cdms}</div>
  `;
  alerts.innerHTML = [
    ...satCdms.map((item) => `
      <div class="alert-chip" style="cursor: pointer; background:${colorForRisk(item.risk)}15;color:${colorForRisk(item.risk)};" onclick="window.selectSatellite(null)">
        ${item.risk} miss ${item.miss_distance_km.toFixed(3)} km at ${(item.tca_seconds / 60).toFixed(1)} min (Click to unselect)
      </div>
    `),
    ...satManeuvers.slice(0, 3).map((item) => `
      <div class="alert-chip" style="cursor: pointer; background:${item.maneuver_type === "EVASION" ? "#ffbe5515" : "#60c4ff15"};color:${item.maneuver_type === "EVASION" ? "#ffbe55" : "#60c4ff"};" onclick="window.selectSatellite(null)">
        ${item.maneuver_type} ${item.event} burn ${item.burn_id}
      </div>
    `),
  ].join("");
}

function updateHud(snapshot) {
  const summary = riskSummary(snapshot);
  document.getElementById("timestamp-label").textContent = new Date(snapshot.timestamp).toLocaleString();
  document.getElementById("speed-label").textContent = autoPlay ? `Auto-step ${stepSeconds}s every poll` : "Auto-step paused";
  document.getElementById("risk-kpi").textContent = `${summary.red} RED`;
  document.getElementById("risk-sub").textContent = `${summary.yellow} YELLOW corridors currently tracked`;
  document.getElementById("burn-kpi").textContent = String(snapshot.recent_maneuvers.length);
  document.getElementById("burn-sub").textContent = `${snapshot.satellites.filter((sat) => sat.status === "EVADING").length} satellites actively deviating`;
}

function render(snapshot) {
  mapRenderer.update(snapshot);
  bullseyeRenderer.render(snapshot.active_conjunctions, selectedSatelliteId);
  heatmapRenderer.render(snapshot);
  ganttRenderer.render(snapshot);
  renderDetails(snapshot);
  renderTicker(snapshot);
  renderEventFeed(snapshot);
  updateHud(snapshot);
}

async function pollSnapshot() {
  try {
    snapshotState = await fetchSnapshot();
    dirty = true;
  } catch (error) {
    document.getElementById("timestamp-label").textContent = error.message;
  } finally {
    setTimeout(pollSnapshot, 2000);
  }
}

async function autoStepLoop() {
  if (!autoPlay || stepping) {
    setTimeout(autoStepLoop, 2000);
    return;
  }
  stepping = true;
  document.getElementById("speed-label").textContent = `Stepping simulation by ${stepSeconds}s`;
  try {
    await stepSimulation(stepSeconds);
    snapshotState = await fetchSnapshot();
    dirty = true;
  } catch (error) {
    document.getElementById("speed-label").textContent = `Step failed: ${error.message}`;
  } finally {
    stepping = false;
    setTimeout(autoStepLoop, 2200);
  }
}

function wireControls() {
  const playToggle = document.getElementById("play-toggle");
  playToggle.addEventListener("click", () => {
    autoPlay = !autoPlay;
    playToggle.textContent = autoPlay ? "Auto-step ON" : "Auto-step OFF";
    playToggle.classList.toggle("active", autoPlay);
    dirty = true;
  });
  document.querySelectorAll("[data-step]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await stepSimulation(Number(button.dataset.step));
        snapshotState = await fetchSnapshot();
        dirty = true;
      } catch (error) {
        document.getElementById("speed-label").textContent = `Manual step failed: ${error.message}`;
      }
    });
  });
  document.querySelectorAll("[data-speed]").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll("[data-speed]").forEach((item) => item.classList.remove("active"));
      chip.classList.add("active");
      stepSeconds = Number(chip.dataset.speed);
      dirty = true;
    });
  });
}

function drawLoop() {
  if (snapshotState && dirty) {
    render(snapshotState);
    dirty = false;
  }
  requestAnimationFrame(drawLoop);
}

mapRenderer.onSelect((satelliteId) => {
  selectedSatelliteId = satelliteId;
  dirty = true;
});

wireControls();
drawLoop();
pollSnapshot();
autoStepLoop();
