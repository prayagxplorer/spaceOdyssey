export async function fetchSnapshot() {
  const response = await fetch("/api/visualization/snapshot");
  if (!response.ok) {
    throw new Error(`Snapshot request failed: ${response.status}`);
  }
  return response.json();
}

export async function stepSimulation(stepSeconds) {
  const response = await fetch("/api/simulate/step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step_seconds: stepSeconds }),
  });
  if (!response.ok) {
    throw new Error(`Simulation step failed: ${response.status}`);
  }
  return response.json();
}
