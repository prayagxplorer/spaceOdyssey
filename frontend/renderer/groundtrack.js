const MAP_TEXTURE =
  "https://upload.wikimedia.org/wikipedia/commons/8/80/World_map_-_low_resolution.svg";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export class GroundTrackRenderer {
  constructor(container) {
    this.container = container;
    this.app = new PIXI.Application({
      resizeTo: container,
      backgroundAlpha: 0,
      antialias: true,
    });
    this.container.appendChild(this.app.view);
    this.background = null;
    this.gridLayer = new PIXI.Graphics();
    this.trailLayer = new PIXI.Graphics();
    this.predictionLayer = new PIXI.Graphics();
    this.terminatorLayer = new PIXI.Graphics();
    this.threatLayer = new PIXI.Graphics();
    this.deviationLayer = new PIXI.Graphics();
    this.debris = new PIXI.ParticleContainer(14000, { position: true, tint: true, alpha: true, scale: true });
    this.satellites = new Map();
    this.trails = new Map();
    this.selectedId = null;
    this.selectHandler = null;
    this.app.stage.addChild(
      this.gridLayer,
      this.trailLayer,
      this.predictionLayer,
      this.terminatorLayer,
      this.threatLayer,
      this.deviationLayer,
      this.debris
    );
    this.loadBackground();
    this.app.ticker.add((ticker) => this.animate(ticker.lastTime / 1000));
    window.addEventListener("resize", () => this.drawGrid());
  }

  async loadBackground() {
    const texture = await PIXI.Assets.load(MAP_TEXTURE);
    this.background = new PIXI.Sprite(texture);
    this.background.width = this.container.clientWidth;
    this.background.height = this.container.clientHeight;
    this.background.alpha = 0.12;
    this.app.stage.addChildAt(this.background, 0);
    this.drawGrid();
  }

  drawGrid() {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.gridLayer.clear();
    this.gridLayer.lineStyle(1, 0x5c8fc2, 0.1);
    for (let lon = -150; lon <= 150; lon += 30) {
      const x = ((lon + 180) / 360) * width;
      this.gridLayer.moveTo(x, 0);
      this.gridLayer.lineTo(x, height);
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      const p1 = this.project(lat, -180);
      const p2 = this.project(lat, 180);
      this.gridLayer.moveTo(p1.x, p1.y);
      this.gridLayer.lineTo(p2.x, p2.y);
    }
  }

  project(lat, lon) {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    const boundedLat = clamp(lat, -85, 85);
    const x = ((lon + 180) / 360) * width;
    const y = height / 2 - (width / (2 * Math.PI)) * Math.log(Math.tan(Math.PI / 4 + (boundedLat * Math.PI) / 360));
    return { x, y: Number.isFinite(y) ? y : height / 2 };
  }

  statusColor(status) {
    if (status === "EVADING") return 0xffbe55;
    if (status === "RECOVERING") return 0x60c4ff;
    if (status === "EOL" || status === "COLLIDED") return 0xff5f72;
    return 0x5ff0b2;
  }

  update(snapshot) {
    const satelliteIds = new Set();
    this.trailLayer.clear();
    this.predictionLayer.clear();
    this.terminatorLayer.clear();
    this.threatLayer.clear();
    this.deviationLayer.clear();
    for (const sat of snapshot.satellites) {
      satelliteIds.add(sat.id);
      const pos = this.project(sat.lat, sat.lon);
      if (!this.satellites.has(sat.id)) {
        const marker = new PIXI.Container();
        marker.eventMode = "static";
        marker.cursor = "pointer";
        // Provide a large explicit hitArea. The actual core radius is 4px, which is extremely difficult to click precisely with a mouse.
        marker.hitArea = new PIXI.Circle(0, 0, 28);
        const glow = new PIXI.Graphics();
        const core = new PIXI.Graphics();
        marker.addChild(glow, core);
        marker.meta = { glow, core, pulse: Math.random() * Math.PI * 2 };
        marker.on("pointertap", () => {
          this.selectedId = sat.id;
          if (this.selectHandler) this.selectHandler(sat.id);
        });
        this.app.stage.addChild(marker);
        this.satellites.set(sat.id, marker);
        this.trails.set(sat.id, []);
      }
      const marker = this.satellites.get(sat.id);
      const color = this.statusColor(sat.status);
      const radius = this.selectedId === sat.id ? 6 : sat.active_cdms ? 5 : 4;
      const { glow, core } = marker.meta;
      glow.clear();
      glow.beginFill(color, 0.12);
      glow.drawCircle(0, 0, radius * 3.1);
      glow.endFill();
      core.clear();
      core.beginFill(color, 0.9);
      core.drawCircle(0, 0, radius);
      core.endFill();
      if (sat.active_cdms) {
        core.lineStyle(1.5, color, 0.7);
        core.drawCircle(0, 0, radius + 9);
      }
      marker.position.set(pos.x, pos.y);
      const track = this.trails.get(sat.id);
      track.push({ x: pos.x, y: pos.y });
      while (track.length > 70) track.shift();
      this.drawTrail(track, color);
      this.drawPrediction(track, sat.alt_km, color);
    }
    for (const [satId, marker] of this.satellites.entries()) {
      if (!satelliteIds.has(satId)) {
        this.app.stage.removeChild(marker);
        this.satellites.delete(satId);
        this.trails.delete(satId);
      }
    }
    this.renderDebris(snapshot.debris_cloud);
    this.drawThreats(snapshot);
    this.drawDeviations(snapshot);
    this.drawTerminator(snapshot.timestamp);
  }

  renderDebris(debrisCloud) {
    this.debris.removeChildren();
    for (const [, lat, lon, alt] of debrisCloud) {
      const sprite = PIXI.Sprite.from(PIXI.Texture.WHITE);
      const pos = this.project(lat, lon);
      sprite.tint = alt > 620 ? 0x7b92ff : 0x6ba7da;
      sprite.alpha = alt > 620 ? 0.24 : 0.38;
      sprite.width = 1.8;
      sprite.height = 1.8;
      sprite.position.set(pos.x, pos.y);
      this.debris.addChild(sprite);
    }
  }

  drawTrail(track, color) {
    if (track.length < 2) return;
    this.trailLayer.lineStyle(1.2, color, 0.22);
    this.trailLayer.moveTo(track[0].x, track[0].y);
    for (let i = 1; i < track.length; i += 1) {
      this.trailLayer.lineTo(track[i].x, track[i].y);
    }
  }

  drawPrediction(track, altKm, color) {
    if (!track.length) return;
    const last = track[track.length - 1];
    const drift = track.length > 4 ? { x: last.x - track[track.length - 5].x, y: last.y - track[track.length - 5].y } : { x: 8, y: -2 };
    const scale = 6 + (altKm - 450) * 0.04;
    this.predictionLayer.lineStyle(1, color, 0.45);
    for (let segment = 0; segment < 7; segment += 1) {
      const startX = last.x + drift.x * segment * 0.72;
      const startY = last.y + drift.y * segment * 0.72;
      if (segment % 2 === 0) {
        this.predictionLayer.moveTo(startX, startY);
        this.predictionLayer.lineTo(startX + drift.x * scale, startY + drift.y * scale);
      }
    }
  }

  drawThreats(snapshot) {
    const bySatellite = new Map(snapshot.satellites.map((sat) => [sat.id, sat]));
    snapshot.active_conjunctions.forEach((cdm, index) => {
      const sat = bySatellite.get(cdm.sat_id);
      if (!sat) return;
      const satPos = this.project(sat.lat, sat.lon);
      const vector = cdm.approach_vector || [0.1, 0.0, 0.0];
      const angle = Math.atan2(vector[1], vector[0]);
      const extent = 50 + Math.max(0, 220 - cdm.tca_seconds / 14);
      const color = cdm.risk === "RED" ? 0xff5f72 : cdm.risk === "YELLOW" ? 0xffbe55 : 0x52f6ff;
      this.threatLayer.lineStyle(2, color, cdm.is_demo ? 0.65 : 0.38);
      this.threatLayer.drawCircle(satPos.x, satPos.y, 18 + index * 2);
      this.threatLayer.moveTo(satPos.x, satPos.y);
      this.threatLayer.lineTo(
        satPos.x + Math.cos(angle) * extent,
        satPos.y + Math.sin(angle) * extent
      );
    });
  }

  drawDeviations(snapshot) {
    const bySatellite = new Map(snapshot.satellites.map((sat) => [sat.id, sat]));
    snapshot.recent_maneuvers.forEach((entry, index) => {
      const sat = bySatellite.get(entry.satellite_id);
      if (!sat) return;
      const satPos = this.project(sat.lat, sat.lon);
      const offset = 24 + index * 4;
      const color = entry.maneuver_type === "EVASION" ? 0xffbe55 : 0x60c4ff;
      this.deviationLayer.lineStyle(2, color, 0.45);
      this.deviationLayer.moveTo(satPos.x, satPos.y);
      this.deviationLayer.bezierCurveTo(
        satPos.x + offset,
        satPos.y - offset,
        satPos.x + offset * 1.4,
        satPos.y + offset * 0.2,
        satPos.x + offset * 1.8,
        satPos.y - offset * 0.4
      );
    });
  }

  drawTerminator(isoTimestamp) {
    const date = new Date(isoTimestamp);
    const day = Math.floor((Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) - Date.UTC(date.getUTCFullYear(), 0, 0)) / 86400000);
    const declination = -23.44 * Math.cos(((360 / 365) * (day + 10) * Math.PI) / 180);
    const subsolarLon = ((date.getUTCHours() + date.getUTCMinutes() / 60) / 24) * -360;
    this.terminatorLayer.lineStyle(2, 0xffffff, 0.14);
    let first = true;
    for (let lon = -180; lon <= 180; lon += 2) {
      const lat = Math.atan(-Math.cos(((lon - subsolarLon) * Math.PI) / 180) / Math.tan((declination * Math.PI) / 180)) * (180 / Math.PI);
      const p = this.project(lat, lon);
      if (first) {
        this.terminatorLayer.moveTo(p.x, p.y);
        first = false;
      } else {
        this.terminatorLayer.lineTo(p.x, p.y);
      }
    }
  }

  animate(time) {
    for (const marker of this.satellites.values()) {
      marker.meta.pulse += 0.04;
      const wobble = 1 + Math.sin(marker.meta.pulse + time) * 0.08;
      marker.scale.set(wobble);
    }
    if (this.background) {
      this.background.width = this.container.clientWidth;
      this.background.height = this.container.clientHeight;
    }
  }

  onSelect(handler) {
    this.selectHandler = handler;
  }
}
