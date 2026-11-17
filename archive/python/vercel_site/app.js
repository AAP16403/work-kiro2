const statusEl = document.getElementById("loading-status");

const PY_FILES = [
  "browser_game.py",
  "config.py",
  "utils.py",
  "logic.py",
  "weapons.py",
  "player.py",
  "projectile.py",
  "powerup.py",
  "hazards.py",
  "layout.py",
  "enemy.py",
  "level.py",
  "physics.py",
  "rpg.py",
  "score.py",
  "particles.py",
  "enemy_behaviors/__init__.py",
  "enemy_behaviors/base.py",
  "enemy_behaviors/chase.py",
  "enemy_behaviors/ranged.py",
  "enemy_behaviors/swarm.py",
  "enemy_behaviors/charger.py",
  "enemy_behaviors/tank.py",
  "enemy_behaviors/spitter.py",
  "enemy_behaviors/flyer.py",
  "enemy_behaviors/engineer.py",
  "enemy_behaviors/bomber.py",
  "enemy_behaviors/bosses/__init__.py",
  "enemy_behaviors/bosses/brute.py",
  "enemy_behaviors/bosses/laser.py",
  "enemy_behaviors/bosses/swarmqueen.py",
  "enemy_behaviors/bosses/thunder.py",
  "enemy_behaviors/bosses/trapmaster.py",
];

function setStatus(text) {
  if (statusEl) {
    statusEl.textContent = text;
  }
}

function ensureDir(pyodide, path) {
  const parts = path.split("/").filter(Boolean);
  let current = "";
  for (const part of parts) {
    current += `/${part}`;
    try {
      pyodide.FS.mkdir(current);
    } catch (_) {
      // Directory already exists.
    }
  }
}

async function loadSource(pyodide, relativePath) {
  const response = await fetch(`./py/${relativePath}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${relativePath}`);
  }
  const text = await response.text();
  const target = `/app/${relativePath}`;
  const parent = target.split("/").slice(0, -1).join("/");
  ensureDir(pyodide, parent);
  pyodide.FS.writeFile(target, text, { encoding: "utf8" });
}

async function boot() {
  try {
    setStatus("Loading Pyodide 0.29.3...");
    const pyodide = await loadPyodide({
      indexURL: "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/",
    });

    setStatus("Staging Python modules...");
    for (let i = 0; i < PY_FILES.length; i += 1) {
      setStatus(`Staging Python modules... ${i + 1}/${PY_FILES.length}`);
      await loadSource(pyodide, PY_FILES[i]);
    }

    setStatus("Starting game runtime...");
    pyodide.runPython(`
import sys
if "/app" not in sys.path:
    sys.path.insert(0, "/app")
`);
    await pyodide.runPythonAsync(`
import browser_game
browser_game.boot()
`);
    setStatus("Python runtime active");
  } catch (error) {
    console.error(error);
    setStatus("Failed to launch browser build");
  }
}

boot();
